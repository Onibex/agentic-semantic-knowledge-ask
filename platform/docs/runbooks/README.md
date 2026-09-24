# Operating the platform

For the people who run ASK rather than use it. Every page assumes access to the host and the
service logs.

- [Local development](local-development.md). Running the services natively instead of in
  Docker, on Windows and PowerShell.
- [Orchestrator troubleshooting](orchestrator-troubleshooting.md). On-call diagnosis for the
  chat backend.
- [Secret scanning and credential rotation](secret-scanning.md). Keeping credentials out of the
  repository, and what to do the day one gets in anyway.
- [Deploy on Kubernetes with Helm](kubernetes-deploy.md). One chart for every cluster. Start here
  and it sends you to the page for your cloud, because only the first two steps differ.
  - [Deploy ASK on AWS EKS](kubernetes-deploy-aws-eks.md). The whole procedure for Amazon EKS,
    top to bottom, including the two things a stock cluster is missing.
  - [Deploy ASK on Azure AKS](kubernetes-deploy-azure-aks.md). The whole procedure for Azure AKS,
    top to bottom, with the free public hostnames and their certificates.
  - [Sign in with SAP Cloud Identity Services](sign-in-with-ias.md). Switch an installed platform
    from the chart's Keycloak to the customer's own SAP identity, on any cloud, with a checklist
    of every IAS setting and a script that checks the ones it can from outside.
  - [Kubernetes reference](kubernetes-reference.md). What the chart is and is not, the capacity
    tables, the failures worth knowing in advance, and the uninstall. Read it when something
    stops, not to install.

To install the platform rather than develop on it, see
[Install and run the platform](../01-installation.md).

---

[← Back to the manual](../README.md)
