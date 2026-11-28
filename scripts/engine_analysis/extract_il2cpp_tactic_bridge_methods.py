#!/usr/bin/env python3
"""Select the managed tactic -> native match-interface bridge methods from IL2CPP output."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

EXACT_PREFIXES = (
    "FM.UI.GenericTacticData$$",
    "FM.UI.RoleDataEntry$$",
    "FM.UI.PlayerInstructionGroup$$",
    "FM.UI.PlayerInstructionOptionEntry$$",
    "FM.UI.TacticTeamInstructionEntry$$",
    "FM.UI.TacticTeamInstructionOptionEntry$$",
    "FM.UI.TacticTeamInstructionData$$",
    "FM.UI.TacticalTweakEntry$$",
    "FM.GamePlugin.Bindings.MarshallingWrappers.SI_Match_IPluginMatchInterface_NativeWrapper$$",
    "FM.GamePlugin.Bindings.MarshallingWrappers.SI_Match_IPluginMatchPlaybackInterface_NativeWrapper$$",
)
MATCH_CLASS_PREFIXES = (
    "FM.Match.MatchPlaybackController$$",
    "FM.Match.MatchSetup$$",
    "FM.Match.MatchModule$$",
    "FM.Match.Match$$",
)
BRIDGE_METHODS = re.compile(
    r"(get_InPossessionRoleID|get_OutOfPossessionRoleID|get_RolePlayerInstructions|"
    r"GetPhaseAndTeamInstructionsEntry|get_PhasesAndTeamInstructions|"
    r"get_InstructionID|get_PhaseID|get_InstructionOptionEntries|get_ExtraInstructionID|"
    r"GetOptionEntry|get_GroupID|get_ExtraGroupID|"
    r"SI_Match_IPluginMatchInterface_(GetInstance|Setup|GetEntitiesInfo|GetPlaybackInterface|"
    r"GetSimulationPeriod|Shutdown)|"
    r"SI_Match_IPluginMatchPlaybackInterface_(OnPlaybackInitialization|PluginDataUpdate|Tick|"
    r"RequestMatchEventsUpdate|GetBallPosition|GetEntityWorldTransform|Seek)|"
    r"FM\.Match\.MatchPlaybackController.*(Initialise|Start|Update|OnEventFromPlugin|"
    r"SetMatchReference|MatchInitialised)|"
    r"FM\.Match\.MatchSetup.*(Setup|Initialise|Load)|"
    r"FM\.Match\.MatchModule.*(Initialise|Setup|Load))",
    re.IGNORECASE,
)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    data=json.loads(args.input.read_text(encoding="utf-8"))
    selected=[]
    for row in data.get("ScriptMethod",[]):
        name=str(row.get("Name",""))
        if not any(name.startswith(p) for p in EXACT_PREFIXES+MATCH_CLASS_PREFIXES):
            continue
        if name.startswith(MATCH_CLASS_PREFIXES) and not BRIDGE_METHODS.search(name):
            continue
        if not name.startswith(MATCH_CLASS_PREFIXES) and not BRIDGE_METHODS.search(name):
            continue
        address=int(row.get("Address",0))
        if address<=0: continue
        selected.append({
            "Address":address,
            "Name":name,
            "Signature":str(row.get("Signature","")),
            "TypeSignature":str(row.get("TypeSignature","")),
        })
    selected.sort(key=lambda x:(x["Address"],x["Name"]))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",encoding="utf-8") as f:
        for x in selected:
            f.write(f'0x{x["Address"]:X}\t{x["Name"]}\t{x["Signature"]}\t{x["TypeSignature"]}\n')
    summary={
        "selected_method_entries":len(selected),
        "unique_native_addresses":len({x["Address"] for x in selected}),
        "selected_classes":sorted({x["Name"].split("$$",1)[0] for x in selected}),
        "output":str(args.output),
    }
    (args.output.parent/"tactic-bridge-methods-summary.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    print(json.dumps(summary,ensure_ascii=False))
    if not selected: raise SystemExit("No tactic bridge methods selected")

if __name__=="__main__": main()
