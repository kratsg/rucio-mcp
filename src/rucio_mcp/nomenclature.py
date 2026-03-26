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
ATLAS Dataset Nomenclature — ATL-COM-GEN-2007-003 (2024 edition)

═══════════════════════════════════════════════════════════════
DATA HIERARCHY
═══════════════════════════════════════════════════════════════
Events ⊂ files ⊂ datasets ⊂ dataset containers ⊂ campaigns.
What physicists call a "dataset" is typically a dataset container in Rucio.

═══════════════════════════════════════════════════════════════
DATA IDENTIFIER (DID) FORMAT
═══════════════════════════════════════════════════════════════
All DIDs have the form:  scope:name

  scope: ≤ 25 chars; allowed chars: a-zA-Z0-9-_.
    - Centrally produced data: scope = project field (e.g. mc20_13TeV)
    - User datasets:           scope = user.<cern_username>
    - Group datasets:          scope = group.<atlas_group>

  name: ≤ 255 chars (containers ≤ 150 chars); chars: a-zA-Z0-9-_.:
    General structure:  project.[otherFields].dataType.[versionTag]
    Containers end with a trailing slash "/" in some Rucio contexts.

═══════════════════════════════════════════════════════════════
FIELD DEFINITIONS
═══════════════════════════════════════════════════════════════
project       ≤ 15 chars. Last 2 digits = year (MC) or run-period year (data).
              Subprojects use underscore: e.g. mc20_13TeV, mc21_13p6TeV.
              MC examples:   mc16_13TeV, mc20_13TeV, mc21_13p6TeV, mc23_13p6TeV
              Data examples: data15_13TeV, data17_13TeV, data18_13TeV,
                             data22_13p6TeV, data23_13p6TeV, data24_13p6TeV

datasetNumber 6-8 digit DSID; identifies the physics process (MC only).
              Job options: https://gitlab.cern.ch/atlas-physics/pmg/mcjoboptions
              Directory pattern: <first3digits>xxx/<datasetNumber>/

physicsShort  ≤ 50 chars. Human-readable process description for MC:
              generator_tune_process (e.g. Sh_2211_Zee_maxHTpTV2_BFilter).

runNumber     8 digits for normal runs (10 digits = timestamp-based run).

streamName    Data-taking stream: physics_Main, physics_ZeroBias,
              physics_MinBias, physics_Egamma, physics_Muons, etc.

periodName    Data period: periodA, periodB, …, periodAllYear, periodAllPeriods.

prodStep      Processing step; determines allowed dataType and AMI tag letter:
              evgen  → EVNT           (tag: e)
              simul  → HITS           (tag: s)
              digit  → RDO            (tag: d)
              recon  → ESD, AOD       (Tier0: f,c,x; ProdSys: r)
              deriv  → DAOD_*         (tag: p)
              merge  → merged formats (Tier0: m; ProdSys: t)
              daq    → RAW            (no AMI tag)
              evtpick→ (any)          (tag: n)

dataType      ≤ 15 chars. Format of stored data:
              RAW         Raw detector readout (Tier0 only)
              TXT         Text (special cases)
              EVNT        Generator-level events (MC)
              HITS        Simulated detector hits (MC)
              RDO         Raw Data Object — digitised hits (MC)
              ESD         Event Summary Data — full reco output
              AOD         Analysis Object Data — reduced from ESD
              DAOD_<grp>  Derived AOD by physics group; ≤ 15 chars total:
                          DAOD_PHYS, DAOD_PHYSLITE (most common for analysis)
                          DAOD_EXOT*, DAOD_SUSY*, DAOD_JETM*, DAOD_EGAM*,
                          DAOD_FTAG*, DAOD_MUON*, DAOD_TRIG*, DAOD_STDM*, …
              NTUP        ROOT ntuple (legacy)
              COND        Conditions data
              PAC         Software package

versionTag    Chain of AMI tags recording processing history (e.g. e8351_s3681_r13144_p5855).
AMITag        letter + number, ≤ 32 chars total.
              Tag letters by processing system:
                Tier-0 (online/express): f=reco, c=reco(comm), x=reco(express),
                                         r=reco(bulk), m=merge
                ProdSys (offline):       e=evgen, s=simul, d=digit, r=reco,
                                         p=group-production/deriv, t=merge, n=evtpick

contVersion   Container version for physics containers:
              Format: [t0pro|repro|pro|grp]NN_vMM[_AMITag]
              Examples: grp15_v01_p5631, pro22_v02, t0pro14_v01

═══════════════════════════════════════════════════════════════
DATASET TYPES AND NAME FORMATS
═══════════════════════════════════════════════════════════════

1. MONTE CARLO (simulation)
   Format:  project.datasetNumber.physicsShort.prodStep.dataType.versionTag
   Example: mc20_13TeV:mc20_13TeV.700320.Sh_2211_Zee_maxHTpTV2_BFilter.deriv.DAOD_PHYS.e8351_s3681_r13144_r13146_p5855

2. REAL DATA — primary datasets
   Format:  project.runNumber.streamName.prodStep.dataType.versionTag
   Example: data18_13TeV:data18_13TeV.00348885.physics_Main.deriv.DAOD_PHYS.r13286_p4910_p5855

3. REAL DATA — physics containers (preferred for analysis)
   Format:  project.periodName.streamName.PhysCont.dataType.contVersion
   Example: data15_13TeV:data15_13TeV.periodAllYear.physics_Main.PhysCont.DAOD_PHYSLITE.grp15_v01_p5631
   Note: "PhysCont" is a literal fixed field separating periodName from dataType.

4. CALIBRATION
   Format:  dataNNN_calib.xxxxxxxx.calibration_<DetectorPart>-<meta-info>.daq.RAW
   Example: data23_calib.00456789.calibration_IDTracks-beamspot-online.daq.RAW

5. USER / GROUP datasets
   User:  user.<cern_username>.<project>.<otherFields>.<dataType>.<versionTag>
   Group: group.<atlas_group>.<project>.<otherFields>.<dataType>.<versionTag>

6. CONDITIONS data
   Format: project.internalCondNumber.datasetUsage.COND

7. DATABASE RELEASE
   Format: ddo.NNNNNNN.[otherFields].vDBReleaseVersion

8. SOFTWARE RELEASE
   Format: sitNN.nnnnnnn.AtlasSWRelease.PAC.vMMmmp[cc]

9. SOFTWARE CONTAINERS (images)
   Format: repositoryUser/repositoryName:cacheName.AMItag-counter

═══════════════════════════════════════════════════════════════
COMMON SCOPES (CAMPAIGNS)
═══════════════════════════════════════════════════════════════
MC:   mc16_13TeV   mc20_13TeV   mc21_13p6TeV   mc23_13p6TeV
Data: data15_13TeV  data16_13TeV  data17_13TeV  data18_13TeV
      data22_13p6TeV  data23_13p6TeV  data24_13p6TeV
User: user.<cern_username>
Group: group.<atlas_group>  (e.g. group.phys-exotics, group.phys-higgs)

═══════════════════════════════════════════════════════════════
FIELD LENGTH LIMITS (from Table 4 of ATL-COM-GEN-2007-003)
═══════════════════════════════════════════════════════════════
scope           ≤ 25 chars
name (dataset)  ≤ 255 chars
name (container)≤ 150 chars
project         ≤ 15 chars
datasetNumber   6-8 digits
physicsShort    ≤ 50 chars
dataType        ≤ 15 chars
AMITag          ≤ 32 chars
versionTag      ≤ 100 chars (chain of AMI tags joined by underscore)
"""
