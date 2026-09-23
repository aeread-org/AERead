import json
def choice(instr,**crit): return {"type":"choice","instructions":instr,"criteria":crit}
Q={"agency":choice("Look only at the focal action (focal_step). How much genuine decision did the agent exercise in it?",
      deliberate_choice="the agent chose among genuinely different options using information in the trajectory (which counterparty to engage, whether to counter, whether to walk, what quantity to award)",
      procedural_default="the step follows the prescribed procedure or the safest default and needed no real decision",
      copy_repeat="the action copies terms it was handed, repeats an earlier action, or restates the agent's own previous action",
      null_inaction="a pass, no-op, or an action with nothing to decide"),
   "outcome_effect":choice("Given the whole trajectory and its outcome, what part did the focal action play in the final outcome?",
      decisive="it directly set or ended the outcome: a signing, an award, a defer, a walk, an accepted counter, or a pass that let a held offer lapse",
      enabling="a prerequisite the final outcome relied on: a quote or sample from a supplier that was later awarded, an offer that produced the hold later signed, an inspection of a listing the agent later signed or walked from",
      informational_unused="it gathered information or made an offer that the final outcome did not use",
      none="no effect on the outcome"),
   "counterfactual":choice("If the focal action were replaced by the safest default for that step (pass, skip, or copying what was handed), would the final outcome change?",yes="the outcome would change materially",marginally="only a small change",no="the outcome would be the same")}
