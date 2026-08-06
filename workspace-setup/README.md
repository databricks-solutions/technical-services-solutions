# Workspace Setup

## Projects

### [AIM User-Ownership Inventory](./aim-user-ownership-inventory/)

A report-only Databricks notebook that inventories every workspace object owned or controlled by a given set of users, so nothing is lost when those users are deleted. Designed as a follow-on to the Automatic Identity Management (AIM) migration prep script: run it on the users prep flags as divergent/failing (commonly former employees) before removing any accounts, to confirm what they still own and transfer anything that must survive.
