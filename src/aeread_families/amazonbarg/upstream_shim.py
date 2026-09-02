"""In-process delegation shim for the pinned ``AmazonPriceHistory`` checkout.

See ``docs/amazonbarg_adapter_spec.md`` section 3.1. Unlike ``tau3_retail``
(a second venv under ``tools/tau2_bridge/provision.sh``), the only import
blocker here is six third-party packages (``requests``, ``jsonlines``,
``matplotlib``, ``seaborn``, ``pandas``, ``fire``) that upstream's ``session.py``
and ``eval.py`` pull in transitively but never touch on the code paths this
adapter exercises (``session.parseReply``, ``eval.Metrics``, and the
zero-dependency ``utils.Action``/``product`` modules). Rather than vendor
``eval.py::Metrics`` (duplicating the exact class "never reimplement" most
wants delegated) or stand up a second venv to work around unused imports,
this module installs stub modules for whichever of the six are actually
absent, imports the pinned source under them, and evicts every touched
upstream module name from ``sys.modules`` again before returning -- so a
second delegated import in the same process re-executes fresh source
rather than reusing a cached module object (required by test plan P3).

Two deliberate departures from the spec's own section 3.1, discovered by
attempting the import for real rather than assuming it would succeed
(recorded here per this build's ground rules: "if reality forces a
deviation, update the spec in the same commit"):

1. **Stub semantics: read vs. use.** Section 3.1 originally said a stub's
   ``__getattr__`` always raises. In practice, ``api_setting.py`` (pulled in
   transitively by ``session.py`` via ``BuyerAgent``/``SellerAgent``) writes
   a plain (non-``from __future__ import annotations``) function signature
   ``-> requests.Response`` on ``vllmAPI.post_http_request``, which Python
   evaluates *eagerly* at class-definition time -- i.e. merely importing
   ``api_setting.py`` reads ``requests.Response``, without ever calling or
   otherwise using it. A stub that raised on every read would make even
   the intended, safe delegation (``session.parseReply``) impossible to
   import. Instead, reading an attribute off a stub module returns an
   inert placeholder (record nothing, raise nothing) so eager annotation
   evaluation stays silent; only *calling* that placeholder -- the one
   thing that could otherwise silently fake a real behavioural result --
   raises :class:`UpstreamShimMissError` and increments the session-scoped
   miss counter that test plan P2(b) asserts stays at ``0``.
2. **``openai`` construction gate.** ``api_setting.py`` builds
   ``api_pool = API(temperature=0.0)`` at *module import time*, whose
   ``__init__`` calls ``openai.OpenAI(api_key='', base_url=...)`` verbatim
   (upstream's own ``openai_keys`` pool is empty in the pinned checkout
   too -- a real key is only ever queued in by a deployer). Against the
   ``openai==2.53.0`` actually installed in this project's venv, an
   explicit empty-string ``api_key`` raises ``OpenAIError: Missing
   credentials`` *locally*, before any network call -- but also before the
   import that only wants ``parseReply`` can complete. This shim
   temporarily substitutes a subclass of the *real* ``openai.OpenAI`` that
   fills in a placeholder key only when the caller passed a falsy one,
   restores the original class immediately after the delegated import
   completes, and the no-network guard below (P2a) proves construction
   still never touches a socket either way -- this changes only whether
   construction raises locally, never upstream's own "no network call"
   property.
"""
from __future__ import annotations

import socket
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, NoReturn


class UpstreamShimMissError(RuntimeError):
    """Delegated upstream code actually used a package this shim stubs out.

    Never caught silently -- turning a silent behavioural gap (this
    adapter quietly getting different behaviour than a fully-installed
    upstream checkout would) into a loud failure the moment it would
    matter.
    """


class _MissCounter:
    """Session-scoped record of every stub placeholder that was *called*.

    Merely reading an attribute off a stub module is not recorded -- see
    the module docstring's point 1. Only a genuine attempted use counts.
    """

    def __init__(self) -> None:
        self._paths: list[str] = []

    def record(self, path: str) -> None:
        self._paths.append(path)

    @property
    def count(self) -> int:
        return len(self._paths)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(self._paths)


_MISS_COUNTER = _MissCounter()

# The complete stub candidate set (spec section 3.1): every package used
# exclusively by upstream code paths this adapter never calls. Only
# whichever of these are actually absent from the current environment get
# a stub module installed; a real, installed package is always preferred.
STUB_CANDIDATE_NAMES: tuple[str, ...] = (
    "requests",
    "jsonlines",
    "matplotlib",
    "seaborn",
    "pandas",
    "fire",
)

# Upstream module names this adapter is known to pull in (directly or
# transitively) through a delegated or direct import. Evicted from
# ``sys.modules`` at the end of every import context so the pinned source
# is re-executed fresh on the next call rather than reusing a cached
# module object.
_UPSTREAM_MODULE_NAMES: tuple[str, ...] = (
    "session",
    "BuyerAgent",
    "SellerAgent",
    "api_setting",
    "product",
    "utils",
    "utils.Action",
    "utils.ActionNarrator",
    "utils.ColoredPrint",
    "utils.HistoryManager",
    "utils.Strategy",
    "utils.format_tokens",
)


def miss_count() -> int:
    """Total number of stub placeholders actually *called* this session."""
    return _MISS_COUNTER.count


def miss_paths() -> tuple[str, ...]:
    """Dotted-path record of every stub placeholder actually called."""
    return _MISS_COUNTER.paths


class _StubUse:
    """A lazy placeholder for one attribute-access chain off a stub module.

    Chaining further attribute access (``stub.a.b.c``) stays silent and
    keeps returning placeholders -- the eager-annotation-evaluation case
    from the module docstring. Calling the placeholder is the one thing
    that would otherwise silently fake upstream behaviour; it always
    raises :class:`UpstreamShimMissError` and records the miss.
    """

    __slots__ = ("_path", "_counter")

    def __init__(self, path: str, counter: _MissCounter) -> None:
        self._path = path
        self._counter = counter

    def __getattr__(self, item: str) -> "_StubUse":
        return _StubUse(f"{self._path}.{item}", self._counter)

    def __call__(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._counter.record(self._path)
        raise UpstreamShimMissError(
            f"delegated upstream code called stubbed {self._path}(...) -- a real "
            "dependency this adapter never provisions and never calls on any path "
            "it exercises"
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<AmazonbargUpstreamStub {self._path}>"


class _StubModule(types.ModuleType):
    """A stub installed into ``sys.modules`` for one absent third-party package.

    ``counter`` defaults to the session-scoped global counter that
    :func:`miss_count` reports; the parameter exists only so a test can
    exercise the miss-detection mechanism itself against an isolated
    counter without polluting the real, suite-wide P2(b) assertion.
    """

    def __init__(self, name: str, *, counter: _MissCounter | None = None) -> None:
        super().__init__(name)
        self._counter = counter if counter is not None else _MISS_COUNTER

    def __getattr__(self, item: str) -> _StubUse:
        return _StubUse(f"{self.__name__}.{item}", self._counter)


def _module_is_really_importable(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


@contextmanager
def _install_missing_stub_modules(names: tuple[str, ...]) -> Iterator[None]:
    installed: list[str] = []
    try:
        for name in names:
            if name in sys.modules:
                continue
            if _module_is_really_importable(name):
                continue
            sys.modules[name] = _StubModule(name)
            installed.append(name)
        yield
    finally:
        for name in installed:
            sys.modules.pop(name, None)


@contextmanager
def _no_network_guard() -> Iterator[None]:
    """P2a: prove a delegated import never attempts a live network connection."""
    original_connect = socket.socket.connect

    def _blocked_connect(self: socket.socket, *args: Any, **kwargs: Any) -> NoReturn:
        raise UpstreamShimMissError(
            f"delegated upstream import attempted a live network connection "
            f"(args={args!r}) -- forbidden for this provider-free adapter"
        )

    socket.socket.connect = _blocked_connect  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]


@contextmanager
def _lenient_openai_construction() -> Iterator[None]:
    """See module docstring point 2. No-op if ``openai`` cannot be imported at all."""
    try:
        import openai
    except ImportError:
        yield
        return

    original_cls = openai.OpenAI

    class _LenientOpenAI(original_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, api_key: str | None = None, **kwargs: Any) -> None:
            if not api_key:
                api_key = "aeread-amazonbarg-shim-unused-key"
            super().__init__(*args, api_key=api_key, **kwargs)

    openai.OpenAI = _LenientOpenAI  # type: ignore[assignment]
    try:
        yield
    finally:
        openai.OpenAI = original_cls  # type: ignore[assignment]


def _insert_path(path: str) -> bool:
    inserted = path not in sys.path
    if inserted:
        sys.path.insert(0, path)
    return inserted


def _remove_path(path: str, inserted: bool) -> None:
    if inserted and path in sys.path:
        sys.path.remove(path)


@contextmanager
def direct_import(upstream_root: Path) -> Iterator[None]:
    """Import zero-third-party-dependency upstream modules (spec 3.1 point 4).

    ``utils/Action.py`` and ``product.py`` import cleanly on their own
    (``re``/``dataclasses``/``json``/``os`` only) -- no stub modules, no
    ``openai`` patch, no miss counter, nothing to shim. Still applies the
    no-network guard as a belt-and-braces check, and evicts every name in
    :data:`_UPSTREAM_MODULE_NAMES` from ``sys.modules`` on exit.
    """
    src = str(upstream_root)
    inserted = _insert_path(src)
    try:
        with _no_network_guard():
            yield
    finally:
        for name in _UPSTREAM_MODULE_NAMES:
            sys.modules.pop(name, None)
        _remove_path(src, inserted)


@contextmanager
def delegated_import(upstream_root: Path) -> Iterator[None]:
    """Import upstream modules that need the stub shim (currently ``session.py``).

    Installs stub modules for whichever of :data:`STUB_CANDIDATE_NAMES` are
    actually absent, blocks socket connections, and patches around the
    ``openai`` empty-api-key construction gate -- all for the duration of
    the ``with`` block only. Every name in :data:`_UPSTREAM_MODULE_NAMES` is
    evicted from ``sys.modules`` on exit regardless of how the block exits.
    """
    src = str(upstream_root)
    inserted = _insert_path(src)
    try:
        with _no_network_guard(), _lenient_openai_construction():
            with _install_missing_stub_modules(STUB_CANDIDATE_NAMES):
                yield
    finally:
        for name in _UPSTREAM_MODULE_NAMES:
            sys.modules.pop(name, None)
        _remove_path(src, inserted)


def import_parse_reply(upstream_root: Path) -> Callable[[str], tuple[str, str, str, str]]:
    """Delegate to the pinned checkout's ``session.parseReply`` (spec section 3.1).

    Returns the upstream function object itself -- never a hand-written
    reimplementation of its three extraction regexes. The returned
    function keeps working after this call returns even though ``session``
    is evicted from ``sys.modules`` immediately: a plain function object
    keeps its defining module's globals (``re`` -- a real stdlib module --
    is all it needs) alive via ``__globals__`` regardless of the module's
    ``sys.modules`` registration.
    """
    with delegated_import(upstream_root):
        import session as _session  # type: ignore[import-not-found]

        return _session.parseReply


def import_camel_amazon_inventories(upstream_root: Path, data_dir: Path) -> list[Any]:
    """Delegate to the pinned checkout's ``product.CamelAmazon`` (spec section 1).

    Returns the real ``list[Inventory]`` upstream's own loader builds --
    the price/cost derivation (``price = max(highest_price, list_price)``,
    ``cost = lowest_price``) and the ``codename = f"{category}_{idx+1}"``
    construction are never reimplemented, only delegated to.
    """
    with direct_import(upstream_root):
        import product as _product  # type: ignore[import-not-found]

        return _product.CamelAmazon(dir=str(data_dir))


def import_action_parser(upstream_root: Path) -> tuple[type, type]:
    """Delegate to the pinned checkout's ``utils.Action`` (``Action``, ``ActionParser``).

    Zero third-party imports of its own (spec section 3.1 point 4) -- no
    shim needed, only the sys.path dance.
    """
    with direct_import(upstream_root):
        from utils.Action import Action as _Action  # type: ignore[import-not-found]
        from utils.Action import ActionParser as _ActionParser  # type: ignore[import-not-found]

        return _Action, _ActionParser


__all__ = [
    "STUB_CANDIDATE_NAMES",
    "UpstreamShimMissError",
    "delegated_import",
    "direct_import",
    "import_action_parser",
    "import_camel_amazon_inventories",
    "import_parse_reply",
    "miss_count",
    "miss_paths",
]
