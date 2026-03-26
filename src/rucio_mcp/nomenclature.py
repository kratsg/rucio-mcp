"""ATLAS dataset nomenclature context for MCP tool descriptions.

Based on ATL-COM-GEN-2007-003 "ATLAS Dataset Nomenclature" (2024 edition).
Embedded into tool docstrings so LLMs understand how to construct valid
Data Identifiers (DIDs) when interacting with Rucio.
"""

from __future__ import annotations

#: Short DID format summary for embedding in tool parameter descriptions.
DID_FORMAT_BRIEF = """\
DID format: scope:name (e.g. 'mc20_13TeV:mc20_13TeV.700320.Sh_2211_Zee.deriv.DAOD_PHYS.e8351_s3681_r13144_p5855').
Wildcards (*) are supported in the name portion.
"""

#: Full ATLAS nomenclature reference for embedding in key tool descriptions.
ATLAS_NOMENCLATURE = """\
ATLAS Data Identifiers (DIDs) use the format scope:name.

DATA HIERARCHY: events ∈ files ∈ datasets ∈ dataset containers ∈ campaigns.
The "dataset" physicists refer to is actually a dataset container in Rucio.

SCOPE: For centrally produced data, scope equals the project field
(e.g. mc16_13TeV, mc20_13TeV, mc21_13p6TeV, data15_13TeV, data18_13TeV).
User datasets: scope = user.<username>. Group: scope = group.<groupname>.

MONTE CARLO (MC) FORMAT:
  project.datasetNumber.physicsShort.prodStep.dataType.AMITags
  Example: mc20_13TeV:mc20_13TeV.700320.Sh_2211_Zee_maxHTpTV2_BFilter.deriv.DAOD_PHYS.e8351_s3681_r13144_r13146_p5855
  - project: mcNN_<energy> (e.g. mc20_13TeV, mc21_13p6TeV)
  - datasetNumber: 6-8 digit DSID identifying the physics process
  - physicsShort: human-readable process description (generator, tune, process)
  - prodStep: evgen, simul, digit, recon, deriv, merge
  - dataType: format (EVNT, HITS, RDO, ESD, AOD, DAOD_PHYS, DAOD_PHYSLITE, etc.)
  - AMITags: processing history chain (see below)

REAL DATA FORMAT:
  project.runNumber.streamName.prodStep.dataType.AMITags
  Example: data18_13TeV:data18_13TeV.00348885.physics_Main.deriv.DAOD_PHYS.r13286_p4910_p5855

PHYSICS CONTAINER FORMAT (preferred for analysis):
  project.periodName.streamName.PhysCont.dataType.contVersion
  Example: data15_13TeV:data15_13TeV.periodAllYear.physics_Main.PhysCont.DAOD_PHYSLITE.grp15_v01_p5631

AMI TAG LETTERS (processing history):
  e=evgen, s=simul, d=digit, r=reco (ProdSys), f=reco (Tier0),
  p=group-production/deriv, m=merge (Tier0), t=merge (ProdSys), n=evtpick

COMMON DATA TYPES:
  RAW, EVNT, HITS, RDO, ESD, AOD, NTUP
  DAOD_PHYS, DAOD_PHYSLITE (most common for analysis)
  DAOD_EXOT*, DAOD_SUSY*, DAOD_JETM*, DAOD_EGAM* (group-specific derivations)

COMMON SCOPES (campaigns):
  MC: mc16_13TeV, mc20_13TeV, mc21_13p6TeV
  Data: data15_13TeV through data24_13p6TeV
  User: user.<cern_username>  Group: group.<atlas_group>
"""
