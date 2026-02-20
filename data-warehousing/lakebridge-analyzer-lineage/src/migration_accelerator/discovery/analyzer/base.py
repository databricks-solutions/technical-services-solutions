# flake8: noqa
from typing import Any, Dict, List, Optional

import pandas as pd  # type: ignore

from migration_accelerator.configs.modules import AnalyzerConfig, LLMConfig
from migration_accelerator.core.llms import LLMManager
from migration_accelerator.utils.files import read_excel
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class SourceAnalyzer:
    def __init__(
        self, analyzer_config: AnalyzerConfig, llm_config: Optional[LLMConfig] = None
    ) -> None:
        self.analyzer_path = analyzer_config.analyzer_file
        self.dialect = analyzer_config.dialect
        self.analyzer_keys = None
        self.llm_config = llm_config

    def parse(self, sheet_names: Optional[List[str]] = None) -> Dict[str, Any]:
        log.info(f"Parsing analyzer file: {self.analyzer_path}")
        data = read_excel(self.analyzer_path, sheet_names=sheet_names)
        log.info(f"Parsed analyzer file: successfully read {len(data)} sheets")
        self.analyzer_keys = list(data.keys())
        return data

    def get_summary(self) -> Dict[str, Any]:
        # TODO: Implement summary parsing using pandas_agent
        return self.get_sheet("Summary").to_dict()  # type: ignore

    def get_sheet(self, sheet_name: str) -> pd.DataFrame:
        log.info(f"Parsing sheet: {sheet_name} from {self.analyzer_path}")
        data = read_excel(self.analyzer_path, sheet_names=[sheet_name])
        log.info(f"Successfully parsed sheet: {sheet_name} from {self.analyzer_path}")
        return data[sheet_name]

    def query(self, query: str) -> Dict[str, Any]:
        # TODO: Implement query parsing using pandas_agent
        if not self.llm_config:
            raise ValueError(
                "LLM configuration is required for querying the analyzer report"
            )
        llm_manager = LLMManager(self.llm_config)
        model = llm_manager.get_llm()

        dataframes = []
        if self.dialect == "sql":
            data = self.parse(
                sheet_names=[
                    "SQL Programs",
                    "SQL Script Categories",
                    "Functions",
                    "Referenced Objects",
                    "Program-Object Xref",
                ]
            )
            dataframes = [data[sheet_name] for sheet_name in data.keys()]
        elif self.dialect == "talend":
            data = self.parse(
                sheet_names=[
                    "Job Details",
                    "Jobs Transformations Xref",
                    "Jobs Transformation List",
                    "Functions",
                ]
            )
            dataframes = [data[sheet_name] for sheet_name in data.keys()]
        elif self.dialect == "informatica":
            data = self.parse(
                sheet_names=[
                    "Mapping Details",
                    "Transformations",
                    "Subjob Info",
                    "Mappings Objects Xref",
                    "Mappings Objects List",
                    "Functions",
                ]
            )
            dataframes = [data[sheet_name] for sheet_name in data.keys()]
        else:
            raise ValueError(f"Unsupported dialect: {self.dialect}")

        # Lazy import to avoid loading langchain agents at module import time
        from migration_accelerator.core.agent_toolkits.pandas import (
            create_pandas_dataframe_agent,
        )
        
        agent = create_pandas_dataframe_agent(
            model,
            dataframes,
            verbose=True,
            allow_dangerous_code=True,
        )
        return agent.invoke(query)

    def get_analysis_report(self) -> Dict[str, Any]:
        # TODO: Implement analysis parsing using pandas_agent
        return self.get_sheet("Analysis Report").to_dict()  # type: ignore

    def get_lineage_report(self) -> Dict[str, Any]:
        # TODO: Implement lineage parsing using pandas_agent
        if not self.llm_config:
            raise ValueError(
                "LLM configuration is required for querying the analyzer report"
            )
        llm_manager = LLMManager(self.llm_config)
        model = llm_manager.get_llm()

        # Use configuration-based sheet selection (get ALL sheets, no fallback)
        from migration_accelerator.app.services.lineage_config import find_all_lineage_sheets
        
        available_sheets = list(self.data.keys())
        lineage_sheets = find_all_lineage_sheets(self.dialect, available_sheets)
        
        if not lineage_sheets:
            raise ValueError(
                f"No lineage sheets found for dialect '{self.dialect}'. "
                f"Available sheets: {available_sheets}"
            )
        
        # Combine data from all sheets
        if len(lineage_sheets) == 1:
            df = self.get_sheet(lineage_sheets[0])
        else:
            # Merge multiple sheets together
            dfs = [self.get_sheet(sheet) for sheet in lineage_sheets]
            df = pd.concat(dfs, ignore_index=True)
        
        return df.to_dict()  # type: ignore

    def extract_metric_value(
        self, sheet_name: str, metric_name: str, value_column: str = "Unnamed: 1"
    ) -> Any:
        """
        Extract a specific metric value from a sheet by matching the metric name.

        Args:
            sheet_name: Name of the Excel sheet to search
            metric_name: The metric name to find (e.g., "Total Mappings")
            value_column: The column containing the value (default: "Unnamed: 1")

        Returns:
            The value associated with the metric, or None if not found
        """
        try:
            df = self.get_sheet(sheet_name)

            # Search for the metric in the first column (usually unnamed or index 0)
            mask = (
                df.iloc[:, 0]
                .astype(str)
                .str.contains(metric_name, case=False, na=False)
            )

            if mask.any():
                # Get the row index where the metric was found
                row_idx = mask.idxmax()
                # Extract the value from the specified column
                if value_column in df.columns:
                    value = df.loc[row_idx, value_column]
                else:
                    # Fallback to second column if named column not found
                    value = df.iloc[row_idx, 1] if len(df.columns) > 1 else None

                log.info(f"Found {metric_name}: {value}")
                return value
            else:
                log.warning(f"Metric '{metric_name}' not found in sheet '{sheet_name}'")
                return None

        except Exception as e:
            log.error(
                f"Error extracting metric '{metric_name}' from sheet '{sheet_name}': {e}"
            )
            return None

    def get_command_line_option(
        self, sheet_name: str, option_flag: str
    ) -> Optional[str]:
        """
        Extract command line option values (e.g., -t INFA).

        Args:
            sheet_name: Name of the Excel sheet to search
            option_flag: The option flag to find (e.g., "-t")

        Returns:
            The value associated with the option flag, or None if not found
        """
        try:
            df = self.get_sheet(sheet_name)

            # Search for the option flag in any column
            for col_idx in range(len(df.columns)):
                mask = (
                    df.iloc[:, col_idx]
                    .astype(str)
                    .str.contains(option_flag, case=False, na=False, regex=False)
                )

                if mask.any():
                    row_idx = mask.idxmax()
                    # Look for the value in the next column
                    if col_idx + 1 < len(df.columns):
                        value = df.iloc[row_idx, col_idx + 1]
                        log.info(f"Found command line option {option_flag}: {value}")
                        return str(value) if pd.notna(value) else None

            log.warning(
                f"Command line option '{option_flag}' not found in sheet '{sheet_name}'"
            )
            return None

        except Exception as e:
            log.error(
                f"Error extracting command line option '{option_flag}' from sheet '{sheet_name}': {e}"
            )
            return None

    def get_job_complexity_breakdown(self, sheet_name: str) -> Dict[str, int]:
        """
        Extract job complexity categorization data.

        Args:
            sheet_name: Name of the Excel sheet to search

        Returns:
            Dictionary with complexity categories and their counts
        """
        complexity_data = {}
        complexity_categories = ["LOW", "MEDIUM", "COMPLEX", "VERY COMPLEX"]

        for category in complexity_categories:
            value = self.extract_metric_value(sheet_name, category)
            if value is not None and pd.notna(value):
                try:
                    complexity_data[category] = int(float(value))
                except (ValueError, TypeError):
                    log.warning(f"Could not convert {category} value to int: {value}")
                    complexity_data[category] = 0

        log.info(f"Job complexity breakdown: {complexity_data}")
        return complexity_data

    def get_key_metrics(self, sheet_name: str) -> Dict[str, Any]:
        """
        Extract key metrics from analyzer reports based on dialect.

        Args:
            sheet_name: Name of the Excel sheet to search

        Returns:
            Dictionary containing key metrics specific to the dialect
        """
        # Determine metrics based on dialect
        if self.dialect and self.dialect.lower() == "sql":
            metrics = self._get_sql_metrics()
        elif self.dialect and self.dialect.lower() == "talend":
            metrics = self._get_talend_metrics()
        else:
            # Default to Informatica/ETL metrics
            metrics = self._get_informatica_metrics()

        key_metrics = {}

        for metric in metrics:
            value = self.extract_metric_value(sheet_name, metric)
            if value is not None and pd.notna(value):
                try:
                    # Try to convert to numeric if possible
                    key_metrics[metric] = float(value)
                except (ValueError, TypeError):
                    key_metrics[metric] = str(value)
            else:
                key_metrics[metric] = None

        log.info(f"Extracted key metrics for {self.dialect} dialect: {key_metrics}")
        return key_metrics

    def _get_sql_metrics(self) -> List[str]:
        """Return SQL-specific metrics to extract."""
        return [
            "Total SQL Scripts",
            "Total FILE Scripts",
            "Total DDLs",
            "Total CTAS Scripts",
            "Total Tables (in scripts)",
            "Total Views",
            "Total Materialized Views",
            "Total Procedures",
            "Total Functions",
            "Total Lines of Code",
            "Total Duplicated SQL Items",
        ]

    def _get_informatica_metrics(self) -> List[str]:
        """Return Informatica/ETL-specific metrics to extract."""
        return [
            "Total Mappings",
            "Total Workflows",
            "Total Mapplets",
            "Total Worklets",
            "Total Nodes",
            "Total Duplicated ETL Items",
        ]

    def _get_talend_metrics(self) -> List[str]:
        """Return Talend-specific metrics to extract."""
        return [
            "Total Jobs",
            "Total Nodes",
            "Total Subjobs",
            "Total Components",
            "Total Contexts",
            "Total Routines",
            "Total Code",
            "Total Documentation",
            "Total Metadata",
        ]

    def get_sql_complexity_breakdown(
        self, sheet_name: str
    ) -> Dict[str, Dict[str, int]]:
        """
        Extract SQL-specific complexity breakdown which has SQL and ETL columns.

        Args:
            sheet_name: Name of the Excel sheet to search

        Returns:
            Dictionary with SQL and ETL complexity breakdowns
        """
        complexity_data = {"SQL": {}, "ETL": {}}
        complexity_categories = ["LOW", "MEDIUM", "COMPLEX", "VERY_COMPLEX"]

        try:
            df = self.get_sheet(sheet_name)

            # Look for the complexity table structure
            for category in complexity_categories:
                # Find the row with this complexity category
                mask = (
                    df.iloc[:, 0]
                    .astype(str)
                    .str.contains(category, case=False, na=False)
                )
                if mask.any():
                    row_idx = mask.idxmax()

                    # SQL column (usually column 1)
                    if len(df.columns) > 1:
                        sql_value = df.iloc[row_idx, 1]
                        try:
                            complexity_data["SQL"][category] = (
                                int(float(sql_value)) if pd.notna(sql_value) else 0
                            )
                        except (ValueError, TypeError):
                            complexity_data["SQL"][category] = 0

                    # ETL column (usually column 2)
                    if len(df.columns) > 2:
                        etl_value = df.iloc[row_idx, 2]
                        try:
                            complexity_data["ETL"][category] = (
                                int(float(etl_value)) if pd.notna(etl_value) else 0
                            )
                        except (ValueError, TypeError):
                            complexity_data["ETL"][category] = 0

            log.info(f"SQL complexity breakdown: {complexity_data}")
            return complexity_data

        except Exception as e:
            log.error(
                f"Error extracting SQL complexity data from sheet '{sheet_name}': {e}"
            )
            return {"SQL": {}, "ETL": {}}
