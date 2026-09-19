-- One-off setup for Project Juno, kept here so the DDL is reviewable.
--
-- `infra/setup.sh unity` does all of this through the CLI, which avoids starting a warehouse.
-- Run this file only if you would rather do it in a SQL editor.
--
-- These objects are deliberately NOT bundle resources: in development mode the bundle prefixes
-- resource names per user (juno.dev_<you>_restaurant), and `bundle destroy` would drop the data.
--
-- Prerequisites, created by `infra/setup.sh azure`:
--   * storage account sajunoprod (ADLS Gen2) with a container named juno
--   * access connector ac-juno-prod, holding Storage Blob Data Contributor on that account
--   * storage credential cred_juno and external location extloc_juno over
--     abfss://juno@sajunoprod.dfs.core.windows.net/

CREATE CATALOG IF NOT EXISTS juno
  MANAGED LOCATION 'abfss://juno@sajunoprod.dfs.core.windows.net/'
  COMMENT 'Project Juno - review analytics with exact counts (AI Engineering capstone)';

CREATE SCHEMA IF NOT EXISTS juno.restaurant
  COMMENT 'Bronze, silver and gold tables, evaluation datasets and the vector index';

CREATE VOLUME IF NOT EXISTS juno.restaurant.raw
  COMMENT 'Raw MEMD-ABSA download; the dataset is not redistributed in the repository';

-- Restrict the catalog to this project's workspace. The metastore is regional and shared with any
-- other workspace in the region, so without this the catalog would be visible from all of them.
ALTER CATALOG juno SET ISOLATION MODE ISOLATED;
