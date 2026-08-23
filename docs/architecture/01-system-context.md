# C4 Level 1 — System context

**Audience:** maintainers, pack authors, release engineers, and safety reviewers
**Classification:** technical architecture

Hex-vision is a repository governance harness. A maintainer runs it locally or in CI; a pack author adds a separately installable stack integration. The harness reads local evidence, uses Git only as repository evidence, and invokes configured scanners or tooling as subprocesses. It never commands a robotics system.

```mermaid
flowchart LR
    maintainer["Repository maintainer\nRuns local checks and reviews findings"]
    pack_author["Pack author\nPublishes a Python pack entry point"]
    ci["GitHub Actions CI\nRuns Makefile targets"]
    hv["Hex-vision\nGovernance harness"]
    repo["Governed repository\nConfig, OpenSpec, decisions, evidence"]
    git["Git\nHistory and configured remotes"]
    github["GitHub\nApproved publication destination"]
    hf["Hugging Face\nApproved publication destination"]
    gitleaks["gitleaks\nSecret scanner"]
    osv["osv-scanner\nLockfile vulnerability scanner"]
    openspec["OpenSpec tooling\nStrict or structural spec validation"]
    external_pack["Installed external pack\nhexvision.packs entry point"]

    maintainer -->|runs CLI / Make targets| hv
    pack_author -->|installs| external_pack
    external_pack -->|is discovered by metadata| hv
    ci -->|invokes only Makefile targets| hv
    hv -->|reads| repo
    hv -->|inspects history and remotes| git
    hv -->|runs verified binary| gitleaks
    hv -->|runs verified binary| osv
    hv -->|validates change package| openspec
    hv -->|normalizes and authorizes release destination| github
    hv -->|normalizes and authorizes release destination| hf
```

A successful check is evidence that a configured policy was evaluated; it is not a release authorization. Publication is separately gated by the shared remote policy and an authoritative `G-PUB` decision-log record.
