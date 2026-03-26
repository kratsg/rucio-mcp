---
icon: lucide/book-open
---

# ATLAS dataset nomenclature

Reference: ATL-COM-GEN-2007-003 "ATLAS Dataset Nomenclature" (2024 edition).

## Data Identifiers (DIDs)

Rucio identifies all data objects via **Data Identifiers** in the form
`scope:name`. For centrally produced ATLAS data the scope equals the project
field (e.g. `mc20_13TeV`, `data18_13TeV`).

**Data hierarchy:**

```
events ∈ files ∈ datasets ∈ dataset containers ∈ campaigns
```

!!! note
    The "dataset" physicists refer to in everyday conversation is usually a
    **dataset container** in Rucio — a collection of datasets from a single
    production campaign. When searching with `rucio_list_dids`, use
    `did_type=container` (the default) to find these.

## Scopes

| Scope pattern           | Used for                                  |
| ----------------------- | ----------------------------------------- |
| `mc16_13TeV`            | Run-2 MC, 13 TeV, ATLAS detector geometry |
| `mc20_13TeV`            | Run-2 MC, 13 TeV, updated geometry        |
| `mc21_13p6TeV`          | Run-3 MC, 13.6 TeV                        |
| `data15_13TeV` – `data24_13p6TeV` | Real collision data by year     |
| `user.<cern_username>`  | Personal user datasets                    |
| `group.<atlas_group>`   | Group-owned datasets                      |

## Monte Carlo format

```
project.datasetNumber.physicsShort.prodStep.dataType.AMITags
```

**Example:**

```
mc20_13TeV:mc20_13TeV.700320.Sh_2211_Zee_maxHTpTV2_BFilter.deriv.DAOD_PHYS.e8351_s3681_r13144_r13146_p5855
```

| Field           | Value                           | Meaning                              |
| --------------- | ------------------------------- | ------------------------------------ |
| `project`       | `mc20_13TeV`                    | MC campaign, Run-2, 13 TeV           |
| `datasetNumber` | `700320`                        | DSID — identifies the physics sample |
| `physicsShort`  | `Sh_2211_Zee_maxHTpTV2_BFilter` | Generator, tune, process             |
| `prodStep`      | `deriv`                         | Production step                      |
| `dataType`      | `DAOD_PHYS`                     | Output format                        |
| `AMITags`       | `e8351_s3681_r13144_r13146_p5855` | Processing history chain           |

## Real data formats

**Primary datasets** (individual runs):

```
project.runNumber.streamName.prodStep.dataType.AMITags
```

```
data18_13TeV:data18_13TeV.00348885.physics_Main.deriv.DAOD_PHYS.r13286_p4910_p5855
```

**Physics containers** (preferred for analysis — groups all runs in a period):

```
project.periodName.streamName.PhysCont.dataType.contVersion
```

```
data15_13TeV:data15_13TeV.periodAllYear.physics_Main.PhysCont.DAOD_PHYSLITE.grp15_v01_p5631
```

Use `periodAllYear` to get the full dataset for a given year, or specific period
letters (`periodA`, `periodB`, …) for subsets.

## AMI tags

AMI tags record the processing history of a dataset as a chain of single-letter
codes followed by a version number:

| Letter | Step                                 |
| ------ | ------------------------------------ |
| `e`    | Event generation (evgen)             |
| `s`    | Detector simulation (simul)          |
| `d`    | Digitisation                         |
| `r`    | Reconstruction (ProdSys)             |
| `f`    | Reconstruction (Tier-0)              |
| `p`    | Group production / derivation        |
| `m`    | Merging (Tier-0)                     |
| `t`    | Merging (ProdSys)                    |
| `n`    | Event picking                        |

## Common data types

| Type            | Description                                           |
| --------------- | ----------------------------------------------------- |
| `DAOD_PHYS`     | Full derivation — most complete, largest              |
| `DAOD_PHYSLITE` | Lightweight derivation — preferred for analysis       |
| `DAOD_EXOT*`    | Exotic physics group derivations                      |
| `DAOD_SUSY*`    | SUSY group derivations                                |
| `AOD`           | Analysis Object Data — pre-derivation                 |
| `ESD`           | Event Summary Data — large, rarely used directly      |
| `EVNT`          | Generator-level events                                |
| `HITS`          | Simulated detector hits                               |
| `RDO`           | Raw detector output                                   |

## Finding MC job options

MC samples are defined by their DSID. Job options live in:

```
https://gitlab.cern.ch/atlas-physics/pmg/mcjoboptions/-/tree/master/<DSIDxxx>/<DSID>
```

where `<DSIDxxx>` is the first three digits of the DSID followed by `xxx`
(e.g. DSID 700320 → `700xxx/700320`).
