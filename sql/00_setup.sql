-- One-off setup for Project Juno.
--
-- These objects are created once and are not managed by the bundle: in development mode a bundled
-- schema would deploy under a per-user name, and `bundle destroy` would drop the data with it.
--
-- The equivalent CLI commands (which avoid starting a warehouse) are:
--   databricks catalogs create juno --storage-root <metastore default storage root>
--   databricks schemas create restaurant juno
--   databricks volumes create juno restaurant raw MANAGED
--
-- On an account with Default Storage enabled, creating a catalog without a location fails with
-- "Metastore storage root URL does not exist". Either create the catalog in the UI (which picks
-- Default Storage for you) or pass the storage root of an existing catalog:
--   databricks catalogs get <existing catalog> -o json | grep storage_root

CREATE CATALOG IF NOT EXISTS juno
  COMMENT 'Project Juno - review analytics with exact counts (AI Engineering capstone)';

CREATE SCHEMA IF NOT EXISTS juno.restaurant
  COMMENT 'Bronze, silver and gold tables, evaluation datasets and the vector index';

CREATE VOLUME IF NOT EXISTS juno.restaurant.raw
  COMMENT 'Raw MEMD-ABSA download; the dataset is not redistributed in the repository';
