# Data Warehousing

## Projects

### [Databricks Metric Views](./dbrx-metric-views/)

A demo showcasing how to use Unity Catalog Metric Views in Databricks to define semantic models directly on the platform. Built on top of the [Retail Store Star Schema Dataset](https://www.kaggle.com/datasets/shrinivasv/retail-store-star-schema-dataset?select=fact_sales_denormalized.csv), it demonstrates how embedding your semantic layer in Databricks provides unified governance through Unity Catalog alongside optimal query performance — eliminating the need for external semantic modeling tools.

### [Genie Space CI/CD](./genie-cicd/)

An automated CI/CD pipeline for promoting Databricks AI/BI Genie spaces across environments. The project uses Databricks Asset Bundles (DABs) to export a Genie space configuration from a Dev workspace, version-control it in Git, and deploy it to a Prod workspace with automatic Unity Catalog catalog/schema reference replacement. It supports both creating new and updating existing Genie spaces, runs on serverless compute by default, and is ready to integrate with CI/CD platforms like GitHub Actions or Azure DevOps.

### [Genie Room Creation](./genie-room-creation/)

A Databricks notebook that enables programmatic creation of AI/BI Genie spaces using the Databricks Python SDK and interactive widgets. It provides a guided, widget-driven experience for configuring a new Genie space — including title, description, warehouse selection, table identifiers, and sample instructions — all without writing manual HTTP requests. The notebook also demonstrates advanced patterns such as listing existing spaces, customizing data sources with sample questions, and leveraging the SDK's built-in authentication and retry capabilities.
