# flake8: noqa: E501
"""Talend corpus - Knowledge base for Talend ETL components and connections.

This module contains comprehensive dictionaries that describe Talend components (nodes)
and connections. These dictionaries are designed to be used by LLM agents to interpret
Talend .item files that have been parsed into JSON format.
"""

TALEND_NODES = {
    "tMap": """
The tMap component is the most powerful and versatile transformation component in Talend ETL. It performs complex data transformation, mapping, joining, filtering, and enrichment operations between multiple input and output data flows.

**Core Functionality:**
- Transforms and maps data between input schemas and output schemas
- Performs complex joins between multiple input flows (main and lookup flows)
- Supports field-level transformations using expressions
- Enables data filtering and conditional routing
- Handles data type conversions and validations

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: The unique identifier for this tMap instance within the job (e.g., "tMap_1")
- **MAP**: Contains the mapping configuration (typically references an external mapping definition)
- **LINK_STYLE**: Defines the visual style of connections (AUTO, BEZIER, DIRECT)
- **TEMPORARY_DATA_DIRECTORY**: Directory path for storing temporary data during complex transformations
- **DIE_ON_ERROR**: Boolean flag indicating whether the job should terminate on transformation errors (true/false)
- **LKUP_PARALLELIZE**: Enables parallel processing of lookup operations for performance optimization
- **LEVENSHTEIN**: Threshold for Levenshtein distance-based fuzzy matching (0 = disabled)
- **JACCARD**: Threshold for Jaccard similarity-based fuzzy matching (0 = disabled)
- **ENABLE_AUTO_CONVERT_TYPE**: Automatically converts data types between input and output to prevent type mismatches
- **ROWS_BUFFER_SIZE**: Number of rows to buffer in memory (default: 2000000) - affects performance and memory usage
- **CHANGE_HASH_AND_EQUALS_FOR_BIGDECIMAL**: Modifies hash and equals methods for BigDecimal types for accurate comparisons
- **CONNECTION_FORMAT**: Specifies the connection format, typically "row" for row-based data flow

**Metadata Structure:**
- **metadata/connector**: Specifies the connection type (FLOW for main output, REJECT for rejected rows)
- **metadata/column**: Array of column definitions with attributes like name, type (e.g., id_String, id_Integer, id_Date), length, precision, nullable, pattern (for dates)

**NodeData Structure:**
- **inputTables**: Defines input flows with attributes:
  - **name**: Name of the input flow
  - **lookupMode**: LOAD_ONCE (load entire dataset once), RELOAD_AT_EACH_ROW (reload for each row), CACHED (use cached data)
  - **matchingMode**: UNIQUE_MATCH (one match), FIRST_MATCH (first matching row), ALL_MATCHES (all matching rows)
  - **mapperTableEntries**: Array of input column definitions with name, type, nullable attributes

- **outputTables**: Defines output flows with attributes:
  - **name**: Name of the output flow
  - **mapperTableEntries**: Array of output column mappings with:
    - **name**: Output column name
    - **expression**: Transformation expression (e.g., "row1.fieldName", "row1.price * 1.1", "TalendDate.getCurrentDate()")
    - **type**: Data type of the output column
    - **nullable**: Whether the column can contain null values

- **varTables**: Defines intermediate variables for calculations that can be reused in expressions

**Common Use Cases:**
- Joining data from multiple sources (e.g., customer data with order data)
- Field-level transformations and calculations
- Data enrichment by looking up reference data
- Filtering rows based on complex conditions
- Data type conversions and formatting
- Aggregating or denormalizing data structures
""",
    "tFileInputDelimited": """
The tFileInputDelimited component reads data from delimited text files (CSV, TSV, or custom-delimited files) and loads it into the Talend data flow for processing.

**Core Functionality:**
- Reads structured data from delimited text files
- Parses rows and fields based on configurable delimiters
- Supports various file encodings and formats
- Handles headers, footers, and empty rows
- Can uncompress files on-the-fly (gzip, zip)

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Full path to the input file (can include context variables)
- **ROW_SEPARATOR**: Character(s) separating rows (e.g., "\\n", "\\r\\n")
- **FIELD_SEPARATOR**: Character(s) separating fields within a row (e.g., ",", ";", "\\t", "|")
- **HEADER**: Number of header rows to skip at the beginning of the file
- **FOOTER**: Number of footer rows to skip at the end of the file
- **LIMIT**: Maximum number of data rows to read (0 or empty = read all)
- **ENCODING**: File character encoding (UTF-8, ISO-8859-1, Windows-1252, etc.)
- **ESCAPE_CHAR**: Character used for escaping special characters (typically "\\")
- **TEXT_ENCLOSURE**: Character used to enclose text fields containing delimiters (typically "\"")
- **CSV_OPTION**: Enables CSV-specific parsing rules
- **UNCOMPRESS**: Indicates if the file is compressed and should be decompressed during reading
- **DIE_ON_ERROR**: Whether to terminate the job on read errors
- **SKIP_EMPTY_ROW**: Skip rows that are empty or contain only whitespace
- **REMOVE_EMPTY_ROW**: Remove empty rows from the data flow
- **TRIM_ALL_COLUMN**: Trim leading and trailing whitespace from all columns
- **ADVANCED_SEPARATOR**: Enables advanced separator configuration (thousands separators, decimal separators)

**Metadata Structure:**
- **metadata/column**: Array of column definitions specifying the schema of the input file:
  - **name**: Column name
  - **type**: Data type (id_String, id_Integer, id_Double, id_Date, id_Boolean, id_Long, id_BigDecimal, etc.)
  - **length**: Maximum length for string types
  - **precision**: Decimal precision for numeric types
  - **pattern**: Date/time format pattern (e.g., "yyyy-MM-dd", "dd/MM/yyyy HH:mm:ss")
  - **nullable**: Whether the column can contain null/empty values
  - **key**: Whether this column is part of a primary key
  - **originalLength**: Original length from source system

**Common Use Cases:**
- Reading CSV exports from databases or applications
- Importing data from flat files for ETL processing
- Loading configuration data from text files
- Processing log files with structured formats
- Batch data ingestion from file-based sources
""",
    "tFileOutputDelimited": """
The tFileOutputDelimited component writes data from the Talend data flow to delimited text files (CSV, TSV, or custom-delimited files).

**Core Functionality:**
- Writes data rows to delimited text files
- Configures field and row delimiters
- Supports file appending or overwriting
- Handles various file encodings
- Can compress output files

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Full path to the output file (can include context variables)
- **ROW_SEPARATOR**: Character(s) separating rows (e.g., "\\n", "\\r\\n")
- **FIELD_SEPARATOR**: Character(s) separating fields within a row (e.g., ",", ";", "\\t", "|")
- **APPEND**: Boolean indicating whether to append to existing file (true) or overwrite (false)
- **INCLUDE_HEADER**: Boolean indicating whether to write column headers as the first row
- **ENCODING**: File character encoding (UTF-8, ISO-8859-1, Windows-1252, etc.)
- **ESCAPE_CHAR**: Character used for escaping special characters
- **TEXT_ENCLOSURE**: Character used to enclose text fields containing delimiters
- **CSV_OPTION**: Enables CSV-specific formatting rules
- **COMPRESS**: Indicates if the output should be compressed (gzip, zip)
- **DELETE_EMPTY_FILE**: Delete the output file if no rows were written
- **FLUSHONROW**: Flush data to disk after each row (slower but safer for critical data)
- **CREATE**: Create the file if it doesn't exist
- **ADVANCED_SEPARATOR**: Enables advanced separator configuration
- **DIE_ON_ERROR**: Whether to terminate the job on write errors

**Metadata Structure:**
- **metadata/column**: Array of column definitions matching the input schema to be written

**Common Use Cases:**
- Exporting query results to CSV files
- Creating data extracts for external systems
- Generating reports in delimited format
- Archiving processed data
- Creating data feeds for downstream applications
""",
    "tFilterRow": """
The tFilterRow component filters incoming data rows based on specified conditions, allowing only rows that meet the criteria to pass through to the main output flow. Rejected rows can optionally be routed to a separate reject flow.

**Core Functionality:**
- Filters data rows based on logical conditions
- Supports multiple conditions with AND/OR logic
- Provides main output for matching rows and optional reject output for non-matching rows
- Enables complex filtering using expressions and functions

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONDITIONS**: Array of filter conditions, each containing:
  - **INPUT_COLUMN**: The column to evaluate
  - **OPERATOR**: Comparison operator (==, !=, <, >, <=, >=, CONTAINS, MATCHES, etc.)
  - **VALUE**: The value to compare against (can be literal or expression)
  - **FUNCTION**: Optional function to apply to the column before comparison
- **LOGICAL_OP**: Logical operator combining multiple conditions (AND, OR)
- **USE_ADVANCED**: Boolean indicating whether to use advanced mode with custom expressions
- **ADVANCED_CONDITION**: Custom Java boolean expression for complex filtering
- **LABEL_FILTER**: Label for the main (filtered) output flow
- **LABEL_REJECT**: Label for the reject output flow

**Common Use Cases:**
- Data quality filtering (removing invalid or incomplete records)
- Business rule application (selecting records meeting specific criteria)
- Data segmentation (routing different data types to different flows)
- Removing duplicates or test data
- Filtering based on date ranges, status codes, or category values
""",
    "tAggregateRow": """
The tAggregateRow component performs aggregate calculations (sum, count, average, min, max, etc.) on grouped data, similar to SQL GROUP BY with aggregate functions.

**Core Functionality:**
- Groups data by specified key columns
- Calculates aggregate functions on grouped data
- Outputs one row per group with aggregated values
- Supports multiple simultaneous aggregations

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **GROUP_BY**: Array of column names to group by
- **OPERATIONS**: Array of aggregate operations, each containing:
  - **INPUT_COLUMN**: Column to aggregate
  - **FUNCTION**: Aggregate function (sum, count, avg, min, max, first, last, count_distinct, list)
  - **OUTPUT_COLUMN**: Name for the aggregated output column
- **USE_FINANCIAL_PRECISION**: Use BigDecimal for financial calculations (prevents rounding errors)
- **REMOVE_DUPLICATE**: Remove duplicate rows based on group by keys

**Common Use Cases:**
- Calculating totals, averages, or counts by category
- Finding min/max values per group
- Data summarization and reporting
- Calculating statistical measures
- Reducing data volume through aggregation
""",
    "tSortRow": """
The tSortRow component sorts incoming data rows based on one or more key columns in ascending or descending order.

**Core Functionality:**
- Sorts data by specified columns
- Supports multiple sort keys with independent sort orders
- Can perform in-memory or external (disk-based) sorting
- Optionally removes duplicate rows

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CRITERIA**: Array of sort criteria, each containing:
  - **COLNAME**: Column name to sort by
  - **ORDER**: Sort order (asc for ascending, desc for descending)
- **SORT_TYPE**: Type of sort algorithm (NUMERIC for numeric columns, STRING for text)
- **SORT_CASE_SENSITIVE**: Whether string sorting should be case-sensitive
- **EXTERNAL_SORT**: Use external (disk-based) sorting for large datasets
- **TEMP_DIR**: Directory for temporary sort files (when using external sort)
- **BUFFER_SIZE**: Memory buffer size for sorting operations

**Common Use Cases:**
- Ordering data for reports
- Preparing data for joins or comparisons
- Sorting before aggregation or deduplication
- Organizing data chronologically or alphabetically
""",
    "tJoin": """
The tJoin component performs SQL-style joins between two data flows (main and lookup) based on specified join keys.

**Core Functionality:**
- Joins two data streams based on common keys
- Supports multiple join types (inner, left outer, right outer)
- Allows multiple join keys
- Outputs combined rows from both inputs

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **JOIN_MODEL**: Type of join (INNER_JOIN, LEFT_OUTER_JOIN, RIGHT_OUTER_JOIN)
- **JOIN_KEY**: Array of key mappings between main and lookup flows
- **USE_HASH**: Use hash-based join algorithm for better performance
- **HASH_SIZE**: Size of hash table for hash joins

**Metadata Structure:**
- Two input connectors: main flow and lookup flow
- Output combines columns from both inputs

**Common Use Cases:**
- Combining customer data with order data
- Enriching transactions with reference data
- Merging data from multiple sources
- Implementing lookups with structured join logic
""",
    "tLogRow": """
The tLogRow component displays data flow contents in the console, logs, or output window. It is primarily used for debugging, monitoring, and validating data during job development and execution.

**Core Functionality:**
- Displays data rows in various formats
- Shows schema and data values
- Helps debug data flow issues
- Can write to console or log files

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **PRINT_CONTENT_WITH_LOG4J**: Use Log4J logging framework instead of System.out
- **TABLE_PRINT**: Display data in table format (aligned columns)
- **VERTICAL**: Display each row vertically (one field per line)
- **PRINT_UNIQUE_NAME**: Include component name in output
- **PRINT_LABEL**: Include a custom label in output
- **PRINT_CONTENT**: Display the actual data content (can be disabled for performance)
- **NB_LINES**: Maximum number of rows to display (0 = display all)
- **FIELD_SEPARATOR**: Character separating fields in basic mode (default: "|")

**Common Use Cases:**
- Debugging data transformations
- Validating data at various stages of the job
- Monitoring data flow during development
- Creating simple data output for testing
- Tracking row counts and data samples
""",
    "tReplicate": """
The tReplicate component duplicates an input data flow to multiple identical output flows, allowing the same data to be processed by different downstream branches.

**Core Functionality:**
- Replicates input data to multiple outputs
- Creates independent copies of the data flow
- Maintains original schema across all outputs
- Enables parallel processing paths

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **NB_OUTPUT**: Number of output flows to create

**Common Use Cases:**
- Sending same data to multiple destinations (e.g., database and file)
- Creating backup or archive flows
- Parallel processing of the same dataset
- Implementing multiple transformations on the same source data
""",
    "tUniqRow": """
The tUniqRow component filters out duplicate rows from a data flow based on specified key columns, keeping only unique rows.

**Core Functionality:**
- Identifies and removes duplicate rows
- Compares rows based on specified key columns
- Can output both unique rows and duplicates
- Requires sorted input for optimal performance

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **UNIQUE_KEY**: Array of column names to determine uniqueness
- **KEEP**: Which row to keep when duplicates found (FIRST, LAST)
- **CASE_SENSITIVE**: Whether string comparisons should be case-sensitive
- **TRIM**: Trim whitespace before comparison

**Common Use Cases:**
- Data deduplication
- Ensuring unique records before loading to database
- Identifying and isolating duplicate records
- Data quality improvement
""",
    "tNormalize": """
The tNormalize component splits a single row containing delimited values in one column into multiple rows, normalizing the data structure.

**Core Functionality:**
- Transforms one row into multiple rows
- Splits delimited values into separate rows
- Maintains other columns constant across generated rows
- Converts denormalized data to normalized format

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **NORMALIZE**: Column containing delimited values to normalize
- **ITEM_SEPARATOR**: Delimiter separating values in the column (e.g., ",", ";", "|")
- **TRIM**: Trim whitespace from extracted values
- **DISCARD_TRAILING_EMPTY_STR**: Ignore empty values at the end

**Common Use Cases:**
- Splitting comma-separated values into separate rows
- Converting multi-value fields to relational format
- Expanding hierarchical data
- Processing arrays stored as delimited strings
""",
    "tDenormalize": """
The tDenormalize component combines multiple rows sharing the same key into a single row, concatenating values from the specified column.

**Core Functionality:**
- Merges multiple rows into one row
- Concatenates values from a specified column
- Groups by key columns
- Converts normalized data to denormalized format

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **DENORMALIZE**: Column whose values will be concatenated
- **MERGE**: Key columns for grouping rows
- **DELIMITER**: Separator for concatenated values (e.g., ",", ";")
- **TRIM**: Trim whitespace from values before concatenation

**Common Use Cases:**
- Creating comma-separated lists from multiple rows
- Denormalizing relational data for reporting
- Aggregating text values
- Creating summary records with concatenated details
""",
    "tReplace": """
The tReplace component replaces specified strings or patterns in column values using search-and-replace operations.

**Core Functionality:**
- Performs string replacement on column values
- Supports literal and regex pattern matching
- Can replace multiple patterns simultaneously
- Modifies data in-place

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **REPLACE**: Array of replacement rules, each containing:
  - **SEARCH**: String or regex pattern to find
  - **REPLACE_WITH**: Replacement string
  - **COLUMN**: Column to perform replacement on
  - **USE_REGEX**: Whether to use regular expressions

**Common Use Cases:**
- Data cleansing and standardization
- Removing unwanted characters
- Formatting phone numbers or addresses
- Correcting known data issues
- Masking sensitive information
""",
    "tExtractRegexFields": """
The tExtractRegexFields component extracts data from string fields using regular expression patterns and creates new columns from the captured groups.

**Core Functionality:**
- Extracts substrings using regex patterns
- Creates new columns from regex capture groups
- Handles complex string parsing
- Validates data against patterns

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FIELD**: Column to extract from
- **REGEX**: Regular expression pattern with capture groups
- **EXTRACTED_FIELDS**: Mapping of capture groups to output columns

**Common Use Cases:**
- Parsing log files or unstructured text
- Extracting data from formatted strings
- Splitting complex identifiers
- Validating and extracting email addresses, URLs, or phone numbers
""",
    "tConvertType": """
The tConvertType component converts data types of columns from one type to another (e.g., String to Integer, Date to String).

**Core Functionality:**
- Converts column data types
- Handles date format conversions
- Manages numeric type conversions
- Provides error handling for invalid conversions

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONVERSIONS**: Array of conversion rules, each specifying:
  - **COLUMN**: Column to convert
  - **TARGET_TYPE**: Target data type
  - **PATTERN**: Format pattern (for date/number conversions)
  - **NULLABLE**: Whether null values are allowed

**Common Use Cases:**
- Preparing data for database loading with specific type requirements
- Converting string dates to Date objects
- Formatting numbers with specific precision
- Type alignment between different systems
""",
    "tJava": """
The tJava component allows execution of custom Java code within a Talend job, providing flexibility for operations not covered by standard components.

**Core Functionality:**
- Executes custom Java code
- Accesses context variables and globalMap
- Implements custom business logic
- Can interact with external libraries

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CODE**: Java code to execute (single block)
- **IMPORT**: Custom Java imports needed for the code

**Common Use Cases:**
- Implementing complex business logic
- Calling external APIs or services
- Custom calculations or validations
- Integration with proprietary Java libraries
- Setting context variables or job parameters
""",
    "tJavaFlex": """
The tJavaFlex component provides three separate sections for custom Java code execution: start code (executed once at beginning), main code (executed for each row), and end code (executed once at end).

**Core Functionality:**
- Three-phase code execution (start, main, end)
- Process data row-by-row in main section
- Initialize resources in start section
- Clean up resources in end section

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **START_CODE**: Code executed once before processing rows
- **MAIN_CODE**: Code executed for each input row
- **END_CODE**: Code executed once after all rows processed
- **IMPORT**: Custom Java imports

**Common Use Cases:**
- Custom row-by-row transformations
- Implementing stateful processing logic
- Complex filtering or routing logic
- Resource management (open connections, close resources)
""",
    "tSetGlobalVar": """
The tSetGlobalVar component sets global variables that can be accessed throughout the job and in other jobs if called as child jobs.

**Core Functionality:**
- Creates or updates global variables
- Makes values available to all components
- Can use expressions to calculate values
- Stores variables in globalMap

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **VARIABLES**: Array of variable definitions:
  - **VAR_NAME**: Variable name
  - **VAR_VALUE**: Variable value (can be expression)
  - **VAR_TYPE**: Data type of the variable

**Common Use Cases:**
- Passing values between job sections
- Storing counters or accumulators
- Sharing configuration values
- Implementing conditional logic based on calculated values
""",
    "tRunJob": """
The tRunJob component executes another Talend job as a child job from within the current (parent) job.

**Core Functionality:**
- Executes child jobs
- Passes context variables to child jobs
- Returns values from child jobs
- Enables job reusability and modularization

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **PROCESS**: Name of the child job to execute
- **CONTEXT_PARAMS**: Context parameters to pass to child job
- **USE_DYNAMIC_JOB**: Execute job dynamically based on variable
- **TRANSMIT_WHOLE_CONTEXT**: Pass all context variables from parent
- **PRINT_PARAMETER**: Print job parameters for debugging
- **DIE_ON_CHILD_ERROR**: Terminate parent job if child fails

**Common Use Cases:**
- Modularizing complex ETL workflows
- Reusing common processing logic
- Implementing parallel job execution
- Creating master-detail job hierarchies
""",
    "tPrejob": """
The tPrejob component marks a section of the job to be executed before the main data flow processing begins.

**Core Functionality:**
- Defines pre-processing logic
- Executes before main job components
- Used for initialization tasks
- Runs only once per job execution

**Common Use Cases:**
- Initializing database connections
- Setting up context variables
- Creating temporary directories or files
- Validating prerequisites
- Logging job start information
""",
    "tPostjob": """
The tPostjob component marks a section of the job to be executed after the main data flow processing completes, regardless of success or failure.

**Core Functionality:**
- Defines post-processing logic
- Executes after main job components
- Runs even if main job fails
- Used for cleanup and finalization tasks

**Common Use Cases:**
- Closing database connections
- Cleaning up temporary files
- Sending completion notifications
- Logging job completion status
- Archiving processed files
""",
    "tDBInput": """
The tDBInput component executes a SQL query against a database and reads the resulting data into the Talend data flow.

**Core Functionality:**
- Executes SELECT queries on databases
- Reads query results row by row
- Supports parameterized queries
- Works with various database types

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Reference to database connection component
- **USE_EXISTING_CONNECTION**: Use connection from another component
- **TABLE**: Table name for simple queries
- **QUERY**: Custom SQL query
- **USE_CURSOR**: Use database cursor for large result sets
- **CURSOR_SIZE**: Number of rows to fetch at a time
- **TRIM_ALL_COLUMN**: Trim whitespace from string columns
- **DIE_ON_ERROR**: Terminate job on query errors

**Common Use Cases:**
- Reading data from database tables
- Executing complex SQL queries
- Extracting data for ETL processing
- Incremental data loading with WHERE clauses
""",
    "tDBOutput": """
The tDBOutput component writes data from the Talend data flow to a database table.

**Core Functionality:**
- Inserts, updates, or deletes database records
- Supports various database operations
- Can perform upserts (insert or update)
- Handles batch processing for performance

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Reference to database connection component
- **USE_EXISTING_CONNECTION**: Use connection from another component
- **TABLE**: Target table name
- **TABLE_ACTION**: Action on table (CREATE, DROP_CREATE, CREATE_IF_NOT_EXISTS, NONE)
- **DATA_ACTION**: Action on data (INSERT, UPDATE, INSERT_OR_UPDATE, UPDATE_OR_INSERT, DELETE)
- **DIE_ON_ERROR**: Terminate job on write errors
- **COMMIT_EVERY**: Number of rows to commit in batches
- **USE_BATCH**: Enable batch processing for better performance
- **BATCH_SIZE**: Number of statements per batch

**Common Use Cases:**
- Loading transformed data into target databases
- Updating existing records
- Implementing CDC (Change Data Capture) patterns
- Bulk data loading with batch processing
""",
    "tDBConnection": """
The tDBConnection component establishes a connection to a database that can be reused by other database components in the job.

**Core Functionality:**
- Opens database connection
- Manages connection pooling
- Shares connection across components
- Supports various database types

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **TYPE**: Database type (MySQL, PostgreSQL, Oracle, SQL Server, etc.)
- **HOST**: Database server hostname or IP
- **PORT**: Database server port
- **DATABASE**: Database name
- **USER**: Database username
- **PASSWORD**: Database password (encrypted in JSON)
- **SCHEMA**: Database schema
- **ADDITIONAL_PARAMS**: Additional JDBC parameters
- **AUTO_COMMIT**: Enable auto-commit mode

**Common Use Cases:**
- Sharing single connection across multiple database operations
- Managing transactions across multiple components
- Optimizing connection handling
""",
    "tDBClose": """
The tDBClose component explicitly closes a database connection that was opened by tDBConnection.

**Core Functionality:**
- Closes database connection
- Releases database resources
- Ensures proper cleanup

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Name of the connection component to close

**Common Use Cases:**
- Ensuring connections are properly closed
- Managing connection lifecycle
- Cleanup in tPostjob sections
""",
    "tDBCommit": """
The tDBCommit component explicitly commits the current database transaction.

**Core Functionality:**
- Commits pending database changes
- Finalizes transactions
- Ensures data persistence

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Name of the connection component to commit

**Common Use Cases:**
- Manual transaction control
- Committing after successful processing
- Implementing custom transaction boundaries
""",
    "tDBRollback": """
The tDBRollback component rolls back the current database transaction, undoing all changes made since the last commit.

**Core Functionality:**
- Rolls back uncommitted changes
- Restores database to previous state
- Used in error handling

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Name of the connection component to rollback

**Common Use Cases:**
- Error recovery in transaction processing
- Implementing rollback on validation failures
- Maintaining data consistency
""",
    "tDBRow": """
The tDBRow component executes SQL statements that don't return result sets (DDL, DML statements like UPDATE, DELETE, CREATE TABLE, etc.).

**Core Functionality:**
- Executes non-SELECT SQL statements
- Performs DDL and DML operations
- Can execute multiple statements
- Returns affected row counts

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Reference to database connection component
- **USE_EXISTING_CONNECTION**: Use connection from another component
- **QUERY**: SQL statement to execute
- **DIE_ON_ERROR**: Terminate job on query errors
- **COMMIT**: Commit after execution

**Common Use Cases:**
- Creating or altering tables
- Executing stored procedures
- Updating or deleting records based on conditions
- Running database maintenance commands
""",
    "tFixedFlowInput": """
The tFixedFlowInput component generates a fixed set of data rows with predefined values, useful for testing or injecting constant data.

**Core Functionality:**
- Generates fixed data rows
- Supports multiple rows with different values
- Defines schema and values
- Used for testing and constants

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **NB_ROWS**: Number of rows to generate
- **VALUES**: Array of row values
- **MODE**: Generation mode (VALUES, FILE)

**Common Use Cases:**
- Testing job logic with sample data
- Injecting lookup values
- Creating reference data
- Generating test datasets
""",
    "tFlowToIterate": """
The tFlowToIterate component converts a data flow (row-based) into iterate links, enabling loop-based processing where each row triggers an iteration.

**Core Functionality:**
- Converts FLOW connection to ITERATE connection
- Enables row-by-row iteration
- Makes row values available as global variables
- Bridges flow and iterate processing models

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FLATTEN_COLUMNS**: Expose columns as global variables

**Common Use Cases:**
- Processing each row individually with separate logic
- Calling child jobs for each row
- File processing loops (one iteration per file)
- Dynamic job execution based on data rows
""",
    "tIterateToFlow": """
The tIterateToFlow component converts iterate-based processing into a data flow, collecting iteration results into rows.

**Core Functionality:**
- Converts ITERATE connection to FLOW connection
- Collects iteration results into rows
- Creates schema from global variables
- Bridges iterate and flow processing models

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **MAPPING**: Maps global variables to output columns

**Common Use Cases:**
- Collecting file processing results into a dataset
- Aggregating iteration results
- Converting iterate-based logic to row-based processing
""",
    "tFileList": """
The tFileList component iterates over files in a directory based on specified patterns, triggering downstream components once per matching file.

**Core Functionality:**
- Lists files in directories
- Filters files by pattern (wildcards, regex)
- Provides file information (path, name, size, date)
- Supports recursive directory traversal

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **DIRECTORY**: Directory path to scan
- **FILES**: File pattern or mask (*.csv, *.txt, etc.)
- **CASE_SENSITIVE**: Case-sensitive file matching
- **INCLUDSUBDIR**: Include subdirectories recursively
- **ORDER**: Sort order for files (NAME, SIZE, DATE)
- **ORDER_ACTION**: Ascending or descending order
- **LIST_MODE**: List mode (FILES, DIRECTORIES, BOTH)

**Common Use Cases:**
- Processing multiple files in a directory
- File-based ETL workflows
- Archive and cleanup jobs
- Dynamic file processing
""",
    "tFileInputExcel": """
The tFileInputExcel component reads data from Excel files (.xls and .xlsx formats) and loads it into the Talend data flow.

**Core Functionality:**
- Reads Excel workbooks
- Supports both legacy (.xls) and modern (.xlsx) formats
- Reads specific sheets or all sheets
- Handles headers and data formatting

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Path to Excel file
- **VERSION**: Excel version (EXCEL_97_2003 for .xls, EXCEL_2007 for .xlsx)
- **ALL_SHEETS**: Read all sheets or specific sheet
- **SHEETNAME**: Name of specific sheet to read
- **HEADER**: Number of header rows to skip
- **FOOTER**: Number of footer rows to skip
- **LIMIT**: Maximum number of rows to read
- **FIRST_COLUMN**: First column to read (A, B, C, etc.)
- **LAST_COLUMN**: Last column to read
- **DIE_ON_ERROR**: Terminate on read errors
- **STOPREAD_ON_EMPTYROW**: Stop reading when empty row encountered
- **TRIMALL**: Trim whitespace from all cells

**Common Use Cases:**
- Reading Excel reports or exports
- Loading configuration data from spreadsheets
- Integrating data from Excel-based systems
- Processing user-submitted Excel files
""",
    "tFileOutputExcel": """
The tFileOutputExcel component writes data from the Talend data flow to Excel files (.xls and .xlsx formats).

**Core Functionality:**
- Creates Excel workbooks
- Writes data to sheets
- Supports formatting and styling
- Can append to existing files

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Path to output Excel file
- **VERSION**: Excel version (EXCEL_97_2003, EXCEL_2007)
- **SHEETNAME**: Name of sheet to create/write
- **APPEND**: Append to existing file
- **INCLUDEHEADER**: Include column headers
- **ADVANCED**: Enable advanced formatting options
- **FONT**: Font settings for cells
- **AUTOSIZECOLUMN**: Auto-size columns to fit content

**Common Use Cases:**
- Creating Excel reports
- Exporting data for business users
- Generating formatted spreadsheets
- Creating data templates
""",
    "tFileInputJSON": """
The tFileInputJSON component reads and parses JSON files, extracting data based on JSONPath expressions.

**Core Functionality:**
- Parses JSON files
- Extracts data using JSONPath queries
- Handles nested JSON structures
- Supports JSON arrays and objects

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Path to JSON file
- **JSONPATH**: JSONPath query to extract data
- **LOOP_QUERY**: JSONPath for array/loop iteration
- **ENCODING**: File character encoding
- **DIE_ON_ERROR**: Terminate on parsing errors

**Common Use Cases:**
- Reading JSON API responses
- Parsing JSON configuration files
- Processing JSON data feeds
- Extracting data from nested JSON structures
""",
    "tFileOutputJSON": """
The tFileOutputJSON component writes data from the Talend data flow to JSON files.

**Core Functionality:**
- Creates JSON files
- Formats data as JSON arrays or objects
- Supports nested structures
- Controls JSON formatting

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Path to output JSON file
- **JSON_STRUCTURE**: JSON output structure configuration
- **ENCODING**: File character encoding
- **CREATE_JSON_IN_ROW**: Create JSON string in a column instead of file
- **PRETTY_PRINT**: Format JSON with indentation for readability

**Common Use Cases:**
- Creating JSON API payloads
- Exporting data in JSON format
- Generating JSON configuration files
- Creating JSON data feeds
""",
    "tFileInputXML": """
The tFileInputXML component reads and parses XML files, extracting data based on XPath expressions.

**Core Functionality:**
- Parses XML files
- Extracts data using XPath queries
- Handles nested XML structures
- Validates against XML schemas

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Path to XML file
- **LOOP_XPATH_QUERY**: XPath query for main data loop
- **MAPPING**: XPath mappings for each output column
- **ENCODING**: File character encoding
- **DIE_ON_ERROR**: Terminate on parsing errors
- **VALIDATE**: Validate XML against schema

**Common Use Cases:**
- Reading XML data feeds
- Parsing XML configuration files
- Processing XML messages
- Extracting data from XML documents
""",
    "tFileOutputXML": """
The tFileOutputXML component writes data from the Talend data flow to XML files.

**Core Functionality:**
- Creates XML files
- Formats data as XML elements
- Supports nested structures
- Generates well-formed XML

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Path to output XML file
- **MAPPING**: XML structure mapping configuration
- **ENCODING**: File character encoding
- **SPLIT_EVERY**: Split into multiple files after N rows
- **ROW_TAG**: Tag name for row elements
- **ROOT_TAG**: Tag name for root element

**Common Use Cases:**
- Creating XML data feeds
- Generating XML messages
- Exporting data in XML format
- Creating XML configuration files
""",
    "tHTTPRequest": """
The tHTTPRequest component makes HTTP/HTTPS requests to web services or APIs and retrieves responses.

**Core Functionality:**
- Makes HTTP GET, POST, PUT, DELETE requests
- Handles HTTP headers and authentication
- Processes response data
- Supports REST APIs

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **METHOD**: HTTP method (GET, POST, PUT, DELETE)
- **URL**: Target URL
- **HEADERS**: HTTP headers
- **BODY**: Request body (for POST/PUT)
- **TIMEOUT**: Request timeout in seconds
- **DIE_ON_ERROR**: Terminate on HTTP errors
- **ENCODING**: Response encoding

**Common Use Cases:**
- Calling REST APIs
- Retrieving data from web services
- Sending data to external systems
- Testing API endpoints
""",
    "tRESTRequest": """
The tRESTRequest component makes RESTful API calls with advanced features for headers, authentication, and response handling.

**Core Functionality:**
- Makes REST API calls
- Supports OAuth and token authentication
- Handles JSON/XML payloads
- Processes API responses

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **METHOD**: HTTP method
- **URL**: API endpoint URL
- **HEADERS**: Request headers
- **BODY**: Request body
- **AUTHENTICATION**: Authentication method (BASIC, OAUTH, TOKEN)
- **DIE_ON_ERROR**: Terminate on errors

**Common Use Cases:**
- Integrating with REST APIs
- Consuming web services
- OAuth authentication flows
- API data extraction
""",
    "tSendMail": """
The tSendMail component sends email messages with optional attachments.

**Core Functionality:**
- Sends emails via SMTP
- Supports HTML and plain text
- Attaches files
- Handles multiple recipients

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **SMTP_HOST**: SMTP server hostname
- **SMTP_PORT**: SMTP server port
- **FROM**: Sender email address
- **TO**: Recipient email addresses
- **SUBJECT**: Email subject
- **MESSAGE**: Email body
- **ATTACH**: File attachments
- **USE_AUTH**: Use SMTP authentication
- **USE_TLS**: Use TLS encryption

**Common Use Cases:**
- Sending job completion notifications
- Emailing reports
- Alert notifications
- Sending data files via email
""",
    "tWarn": """
The tWarn component generates warning messages that are displayed during job execution without stopping the job.

**Core Functionality:**
- Displays warning messages
- Continues job execution
- Logs warnings to console/log files
- Can include variable values in messages

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **MESSAGE**: Warning message text
- **PRIORITY**: Warning priority level
- **CODE**: Warning code for categorization

**Common Use Cases:**
- Notifying about non-critical issues
- Logging validation warnings
- Alerting about data quality issues
- Debugging and monitoring
""",
    "tDie": """
The tDie component terminates the job execution immediately with a specified error message and exit code.

**Core Functionality:**
- Stops job execution
- Sets exit code
- Logs error message
- Triggers error handling

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **MESSAGE**: Error message text
- **PRIORITY**: Error priority level
- **CODE**: Exit code (non-zero indicates error)
- **EXIT_JVM**: Whether to exit the JVM

**Common Use Cases:**
- Stopping job on critical errors
- Implementing validation checks with hard stops
- Error handling and recovery
- Conditional job termination
""",
    "tTeradataConnection": """
The tTeradataConnection component establishes a connection to a Teradata database that can be reused by other Teradata components in the job.

**Core Functionality:**
- Opens connection to Teradata database
- Manages connection pooling and reuse
- Shares connection across multiple Teradata components
- Supports various authentication methods

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **HOST**: Teradata server hostname or IP address
- **PORT**: Teradata server port (typically 1025)
- **DATABASE**: Database name or schema
- **USERNAME**: Database username for authentication
- **PASSWORD**: Database password (encrypted in JSON)
- **TMODE**: Transaction mode (ANSI or TERA)
- **CHARSET**: Character set encoding (UTF8, UTF16, etc.)
- **AUTO_COMMIT**: Enable auto-commit mode (true/false)
- **QUERY_BAND**: Query band settings for Teradata workload management
- **USE_EXISTING_CONNECTION**: Reference to existing connection component
- **ADDITIONAL_PARAMS**: Additional JDBC connection parameters

**Common Use Cases:**
- Sharing single connection across multiple Teradata operations
- Managing transactions across multiple Teradata components
- Optimizing connection handling for Teradata databases
- Setting query band for workload management
""",
    "tTeradataInput": """
The tTeradataInput component executes a SQL query against a Teradata database and reads the resulting data into the Talend data flow.

**Core Functionality:**
- Executes SELECT queries on Teradata databases
- Reads query results row by row
- Supports parameterized queries and dynamic SQL
- Leverages Teradata-specific optimizations (FastExport, FastLoad)

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Reference to tTeradataConnection component
- **USE_EXISTING_CONNECTION**: Use connection from another component (true/false)
- **TABLE**: Table name for simple queries
- **QUERY**: Custom SQL query (supports Teradata-specific SQL)
- **SCHEMA_DB**: Schema/database name
- **USE_CURSOR**: Use database cursor for large result sets
- **CURSOR_SIZE**: Number of rows to fetch at a time
- **TRIM_ALL_COLUMN**: Trim whitespace from string columns
- **DIE_ON_ERROR**: Terminate job on query errors
- **ENABLE_PARALLEL**: Enable parallel data extraction
- **USE_FASTEXPORT**: Use Teradata FastExport utility for better performance

**Metadata Structure:**
- **metadata/column**: Array of column definitions matching the query result schema

**Common Use Cases:**
- Extracting data from Teradata tables
- Executing complex Teradata SQL queries
- Incremental data loading with WHERE clauses
- Large-scale data extraction using FastExport
""",
    "tTeradataOutput": """
The tTeradataOutput component writes data from the Talend data flow to a Teradata database table.

**Core Functionality:**
- Inserts, updates, or deletes Teradata records
- Supports various database operations and bulk loading
- Leverages Teradata FastLoad and MultiLoad utilities
- Handles batch processing for optimal performance

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Reference to tTeradataConnection component
- **USE_EXISTING_CONNECTION**: Use connection from another component
- **TABLE**: Target table name
- **SCHEMA_DB**: Schema/database name
- **TABLE_ACTION**: Action on table (CREATE, DROP_CREATE, CREATE_IF_NOT_EXISTS, CLEAR, TRUNCATE, NONE)
- **DATA_ACTION**: Action on data (INSERT, UPDATE, INSERT_OR_UPDATE, UPDATE_OR_INSERT, DELETE)
- **DIE_ON_ERROR**: Terminate job on write errors
- **COMMIT_EVERY**: Number of rows to commit in batches
- **USE_BATCH**: Enable batch processing for better performance
- **BATCH_SIZE**: Number of statements per batch
- **USE_FASTLOAD**: Use Teradata FastLoad utility for bulk inserts
- **USE_MULTILOAD**: Use Teradata MultiLoad for bulk operations
- **ERROR_TABLE**: Error table name for FastLoad/MultiLoad operations
- **WORK_TABLE**: Work table name for MultiLoad operations

**Common Use Cases:**
- Loading transformed data into Teradata tables
- Bulk data loading using FastLoad/MultiLoad
- Updating existing Teradata records
- Implementing CDC patterns with Teradata
""",
    "tTeradataClose": """
The tTeradataClose component explicitly closes a Teradata database connection that was opened by tTeradataConnection.

**Core Functionality:**
- Closes Teradata database connection
- Releases database resources
- Ensures proper cleanup of Teradata sessions

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Name of the tTeradataConnection component to close

**Common Use Cases:**
- Ensuring Teradata connections are properly closed
- Managing connection lifecycle in complex jobs
- Cleanup in tPostjob sections
- Releasing Teradata sessions and resources
""",
    "tMysqlConnection": """
The tMysqlConnection component establishes a connection to a MySQL database that can be reused by other MySQL components in the job.

**Core Functionality:**
- Opens connection to MySQL/MariaDB database
- Manages connection pooling and reuse
- Shares connection across multiple MySQL components
- Supports SSL connections

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **HOST**: MySQL server hostname or IP address
- **PORT**: MySQL server port (typically 3306)
- **DATABASE**: Database name
- **USERNAME**: Database username for authentication
- **PASSWORD**: Database password (encrypted in JSON)
- **ENCODING**: Character encoding (UTF-8, latin1, etc.)
- **AUTO_COMMIT**: Enable auto-commit mode (true/false)
- **USE_SSL**: Enable SSL/TLS encrypted connection
- **SSL_TRUST_STORE**: Path to SSL trust store file
- **ADDITIONAL_PARAMS**: Additional JDBC connection parameters (e.g., useServerPrepStmts=true)

**Common Use Cases:**
- Sharing single connection across multiple MySQL operations
- Managing transactions across multiple MySQL components
- Optimizing connection handling for MySQL databases
- Secure connections using SSL/TLS
""",
    "tMysqlInput": """
The tMysqlInput component executes a SQL query against a MySQL database and reads the resulting data into the Talend data flow.

**Core Functionality:**
- Executes SELECT queries on MySQL/MariaDB databases
- Reads query results row by row
- Supports parameterized queries
- Optimizes for MySQL-specific features

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Reference to tMysqlConnection component
- **USE_EXISTING_CONNECTION**: Use connection from another component
- **TABLE**: Table name for simple queries
- **QUERY**: Custom SQL query (supports MySQL-specific SQL)
- **SCHEMA_DB**: Schema/database name
- **USE_CURSOR**: Use database cursor for large result sets
- **CURSOR_SIZE**: Number of rows to fetch at a time (fetchSize)
- **TRIM_ALL_COLUMN**: Trim whitespace from string columns
- **DIE_ON_ERROR**: Terminate job on query errors
- **ENABLE_STREAM**: Enable streaming result sets for very large datasets
- **USE_PREPARED_STATEMENT**: Use prepared statements for parameterized queries

**Metadata Structure:**
- **metadata/column**: Array of column definitions matching the query result schema

**Common Use Cases:**
- Extracting data from MySQL tables
- Executing MySQL queries with specific optimizations
- Incremental data loading with WHERE clauses
- Reading large datasets using streaming mode
""",
    "tMysqlClose": """
The tMysqlClose component explicitly closes a MySQL database connection that was opened by tMysqlConnection.

**Core Functionality:**
- Closes MySQL database connection
- Releases database resources
- Ensures proper cleanup

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Name of the tMysqlConnection component to close

**Common Use Cases:**
- Ensuring MySQL connections are properly closed
- Managing connection lifecycle
- Cleanup in tPostjob sections
- Preventing connection leaks
""",
    "tOracleConnection": """
The tOracleConnection component establishes a connection to an Oracle database that can be reused by other Oracle components in the job.

**Core Functionality:**
- Opens connection to Oracle database
- Manages connection pooling and reuse
- Shares connection across multiple Oracle components
- Supports various Oracle authentication methods

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **HOST**: Oracle server hostname or IP address
- **PORT**: Oracle listener port (typically 1521)
- **DATABASE**: Database name or SID
- **SCHEMA**: Oracle schema name
- **USERNAME**: Database username for authentication
- **PASSWORD**: Database password (encrypted in JSON)
- **CONNECTION_TYPE**: Connection type (SID, SERVICE_NAME, TNS)
- **TNS_FILE**: Path to tnsnames.ora file (for TNS connection)
- **AUTO_COMMIT**: Enable auto-commit mode (true/false)
- **ADDITIONAL_PARAMS**: Additional JDBC connection parameters
- **USE_WALLET**: Use Oracle Wallet for authentication

**Common Use Cases:**
- Sharing single connection across multiple Oracle operations
- Managing transactions across multiple Oracle components
- Optimizing connection handling for Oracle databases
- Using Oracle Wallet for secure authentication
""",
    "tOracleInput": """
The tOracleInput component executes a SQL query against an Oracle database and reads the resulting data into the Talend data flow.

**Core Functionality:**
- Executes SELECT queries on Oracle databases
- Reads query results row by row
- Supports parameterized queries and bind variables
- Leverages Oracle-specific optimizations

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Reference to tOracleConnection component
- **USE_EXISTING_CONNECTION**: Use connection from another component
- **TABLE**: Table name for simple queries
- **QUERY**: Custom SQL query (supports Oracle-specific SQL and PL/SQL)
- **SCHEMA_DB**: Schema/database name
- **USE_CURSOR**: Use database cursor for large result sets
- **CURSOR_SIZE**: Number of rows to fetch at a time (arraySize)
- **TRIM_ALL_COLUMN**: Trim whitespace from string columns
- **DIE_ON_ERROR**: Terminate job on query errors
- **USE_PREPARED_STATEMENT**: Use prepared statements with bind variables
- **ENABLE_PARALLEL_QUERY**: Enable Oracle parallel query execution

**Metadata Structure:**
- **metadata/column**: Array of column definitions matching the query result schema

**Common Use Cases:**
- Extracting data from Oracle tables
- Executing complex Oracle SQL and PL/SQL queries
- Incremental data loading with bind variables
- Large-scale data extraction using parallel queries
""",
    "tOracleRow": """
The tOracleRow component executes SQL statements that don't return result sets against an Oracle database (DDL, DML statements like UPDATE, DELETE, CREATE TABLE, PL/SQL blocks, etc.).

**Core Functionality:**
- Executes non-SELECT SQL statements on Oracle
- Performs DDL and DML operations
- Executes PL/SQL blocks and stored procedures
- Returns affected row counts

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CONNECTION**: Reference to tOracleConnection component
- **USE_EXISTING_CONNECTION**: Use connection from another component
- **QUERY**: SQL statement or PL/SQL block to execute
- **DIE_ON_ERROR**: Terminate job on query errors
- **COMMIT**: Commit after execution (true/false)
- **USE_PREPARED_STATEMENT**: Use prepared statements for parameterized queries
- **PROPAGATE_RECORD_COUNT**: Propagate the number of affected rows to globalMap
- **NB_RETRIES**: Number of retries on failure
- **SLEEP_TIME**: Wait time between retries (milliseconds)

**Common Use Cases:**
- Creating or altering Oracle tables and objects
- Executing Oracle stored procedures
- Updating or deleting records based on conditions
- Running Oracle PL/SQL blocks
- Database maintenance commands
""",
    "tHashInput": """
The tHashInput component reads data from an in-memory hash structure that was previously created by tHashOutput, enabling data reuse within the same job without re-reading from external sources.

**Core Functionality:**
- Reads data from in-memory hash table
- Provides fast access to cached data
- Enables data reuse across multiple subjobs
- No disk I/O required after initial hash creation

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **HASH_KEY**: Name of the hash table to read from (must match tHashOutput)
- **SCHEMA**: Schema definition for the data being read

**Behavior:**
- Reads data that was stored by a corresponding tHashOutput component
- Data is retrieved from memory, providing very fast access
- The hash table persists within the job execution
- Multiple tHashInput components can read from the same hash table

**Common Use Cases:**
- Reusing lookup data across multiple subjobs without re-querying
- Caching reference data for repeated access
- Improving performance by avoiding redundant data reads
- Sharing data between different parts of the same job
- Creating temporary in-memory datasets
""",
    "tHashOutput": """
The tHashOutput component stores incoming data flow into an in-memory hash structure, making it available for subsequent access by tHashInput components.

**Core Functionality:**
- Stores data flow in memory as hash table
- Enables data caching for reuse within job
- Provides fast in-memory storage
- No disk I/O required

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **HASH_KEY**: Name of the hash table to create (must be unique)
- **SCHEMA**: Schema definition for the data being stored

**Behavior:**
- Receives data from input flow
- Stores all rows in an in-memory hash table
- Makes data available to tHashInput components with matching HASH_KEY
- Data remains in memory for the duration of job execution
- Automatically cleared when job completes

**Common Use Cases:**
- Caching lookup data for repeated access
- Storing reference data in memory
- Avoiding redundant database queries
- Creating temporary in-memory datasets
- Sharing data between subjobs without file I/O
- Performance optimization for frequently accessed data
""",
    "tUnite": """
The tUnite component merges multiple input data flows with the same schema into a single output flow, performing a UNION ALL operation.

**Core Functionality:**
- Combines multiple input flows into one output
- Appends rows from all inputs sequentially
- Requires compatible schemas across inputs
- Performs UNION ALL (includes duplicates)

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **SCHEMA**: Schema definition for inputs and output (must be compatible)
- **ENABLE_PARALLEL**: Enable parallel processing of input flows

**Behavior:**
- Accepts multiple input connections (typically 2 or more)
- Reads rows from all inputs and outputs them sequentially
- Does NOT remove duplicates (UNION ALL behavior)
- Order of rows depends on input processing order
- All inputs must have compatible schemas

**Schema Requirements:**
- All input flows must have the same schema structure
- Column names, types, and order should match
- Length and precision can vary but should be compatible

**Difference from Other Components:**
- **tUnite**: Combines flows (UNION ALL) - keeps duplicates
- **tUniqRow**: Removes duplicates from a single flow
- **tMap**: Can combine flows with joins/lookups and transformations

**Common Use Cases:**
- Merging data from multiple sources with same structure
- Combining results from parallel processing paths
- Appending data from multiple files or tables
- Consolidating data streams before output
- Creating unified datasets from distributed sources
""",
    "tLogCatcher": """
The tLogCatcher component captures log messages, warnings, and errors generated during job execution, making them available as a data flow for logging, monitoring, or error handling.

**Core Functionality:**
- Catches log messages from job execution
- Captures errors, warnings, and info messages
- Outputs log events as data rows
- Enables custom log processing and storage

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CATCH_COMPONENT_MESSAGES**: Capture messages from component execution (true/false)
- **CATCH_JAVA_EXCEPTION**: Capture Java exceptions (true/false)
- **CATCH_USER_EXCEPTION**: Capture user-defined exceptions (true/false)
- **CATCH_WARNING**: Capture warning messages (true/false)

**Metadata Structure (Standard Log Schema):**
The tLogCatcher outputs rows with the following standard columns:
- **moment**: Timestamp when the log message was generated (Date type)
- **pid**: Process ID of the current execution (String type)
- **root_pid**: Root process ID (String type)
- **father_pid**: Parent process ID (String type)
- **project**: Project name (String type)
- **job**: Job name (String type)
- **context**: Context name (String type)
- **priority**: Log priority/severity level (Integer: 4=ERROR, 5=WARN, 6=INFO)
- **type**: Message type (String type)
- **origin**: Component that generated the message (String type)
- **message**: Log message content (String type)
- **code**: Message code (Integer type)

**Behavior:**
- Typically placed in a separate subjob (often in tPrejob or as standalone subjob)
- Runs continuously during job execution to capture log events
- Does not stop the job when errors are caught
- Can be connected to database output, file output, or monitoring systems

**Common Use Cases:**
- Logging all job messages to database for auditing
- Writing errors and warnings to log files
- Implementing custom error notification systems
- Capturing job statistics and execution details
- Creating job execution dashboards
- Debugging complex jobs by capturing all messages
- Compliance and audit trail requirements
""",
    "tJavaRow": """
The tJavaRow component allows execution of custom Java code for each row in the data flow, enabling row-by-row custom transformations and business logic implementation.

**Core Functionality:**
- Executes custom Java code for each input row
- Processes data row-by-row with custom logic
- Accesses and modifies row data using Java
- Implements complex transformations not available in standard components

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **CODE**: Java code to execute for each row
- **IMPORT**: Custom Java imports required for the code

**Behavior:**
- Receives input rows one at a time
- Executes the custom Java code for each row
- Can access input row columns using: input_row.columnName
- Can set output row columns using: output_row.columnName = value
- Code is executed within the row processing loop
- Can access globalMap and context variables

**Code Structure:**
The Java code has access to:
- **input_row**: Input row object with all input columns as properties
- **output_row**: Output row object to set output column values
- **globalMap**: Global variables map
- **context**: Context variables
- Standard Java libraries and imported classes

**Metadata Structure:**
- Input schema defines available input_row columns
- Output schema defines required output_row columns

**Common Use Cases:**
- Complex row-level calculations not possible with expressions
- Custom data validation logic
- Integration with external Java libraries per row
- Implementing proprietary business rules
- Complex string manipulations or parsing
- Custom data type conversions
- Calling external methods or APIs per row
""",
    "tFileInputPositional": """
The tFileInputPositional component reads data from fixed-width positional files where each field occupies a specific character position range, rather than being delimited.

**Core Functionality:**
- Reads fixed-width/positional format files
- Extracts fields based on character positions
- Handles mainframe and legacy system file formats
- Supports various encodings including EBCDIC

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **FILENAME**: Full path to the input file
- **ENCODING**: File character encoding (UTF-8, ISO-8859-1, EBCDIC, etc.)
- **ROW_SEPARATOR**: Character(s) separating rows
- **HEADER**: Number of header rows to skip
- **FOOTER**: Number of footer rows to skip
- **LIMIT**: Maximum number of data rows to read
- **DIE_ON_ERROR**: Terminate job on read errors
- **TRIM_ALL_COLUMN**: Trim whitespace from all extracted fields
- **ENABLE_DECODE**: Enable character decoding (for EBCDIC files)

**Metadata Structure:**
- **metadata/column**: Array of column definitions with positional information:
  - **name**: Column name
  - **type**: Data type (id_String, id_Integer, etc.)
  - **position**: Starting character position (0-based or 1-based)
  - **length**: Number of characters for this field
  - **precision**: Decimal precision for numeric types
  - **nullable**: Whether the field can be empty
  - **pattern**: Date/time format pattern

**Positional Field Definition:**
Each column is defined by its starting position and length:
- Position 0-9: First field (10 characters)
- Position 10-29: Second field (20 characters)
- Position 30-35: Third field (6 characters)

**Common Use Cases:**
- Reading mainframe data files (fixed-width format)
- Processing legacy system exports
- Reading COBOL copybook-formatted files
- Importing data from systems that produce fixed-width files
- Reading flat files with positional data layouts
- Processing EBCDIC-encoded files from mainframes
""",
    "tSchemaComplianceCheck": """
The tSchemaComplianceCheck component validates incoming data rows against a defined schema, checking for data type compliance, format validation, and constraint violations.

**Core Functionality:**
- Validates data against schema definitions
- Checks data type compliance
- Validates data formats and patterns
- Enforces length and precision constraints
- Separates compliant and non-compliant rows

**Key Element Parameters in JSON:**
- **UNIQUE_NAME**: Unique identifier for this component instance
- **SCHEMA**: Expected schema definition for validation
- **DIE_ON_ERROR**: Terminate job on validation errors (true/false)
- **STORE_REJECTED_ROWS**: Output rejected rows to reject flow (true/false)
- **CHECK_ALL_COLUMNS**: Validate all columns (true) or stop at first error (false)
- **ENABLE_STRING_LENGTH_CHECK**: Validate string length constraints
- **ENABLE_DECIMAL_PRECISION_CHECK**: Validate decimal precision
- **ENABLE_DATE_PATTERN_CHECK**: Validate date format patterns

**Validation Checks:**
- **Data Type**: Verifies data can be converted to expected type (e.g., numeric string to Integer)
- **String Length**: Checks if string length exceeds defined maximum length
- **Decimal Precision**: Validates decimal numbers have correct precision and scale
- **Date Format**: Verifies dates match the specified pattern
- **Nullable Constraints**: Checks if non-nullable fields contain null values
- **Numeric Range**: Validates numeric values fit within type constraints

**Output Flows:**
- **Main Flow**: Rows that pass all validation checks
- **Reject Flow**: Rows that fail validation (if STORE_REJECTED_ROWS is true)

**Metadata Structure:**
- Input schema defines the data to validate
- Output schema matches input schema for compliant rows
- Reject schema includes additional error information columns:
  - **errorCode**: Code indicating the type of error
  - **errorMessage**: Description of the validation failure
  - **errorColumn**: Name of the column that failed validation

**Common Use Cases:**
- Data quality checks before loading to database
- Validating imported data against expected formats
- Identifying and isolating bad data records
- Implementing data governance rules
- Pre-processing validation for data warehouses
- Ensuring data type compatibility before transformations
- Quality assurance in ETL pipelines
""",
}

TALEND_CONNECTIONS = {
    "FLOW": """
The FLOW connection (also called Main Row connection) represents the primary data flow between components in Talend. It transfers data records row-by-row from one component to another, carrying the full dataset through the transformation pipeline.

**Characteristics:**
- **Data Transfer**: Transmits actual data rows between components
- **Schema Propagation**: The schema (column definitions) is passed from source to target component
- **Sequential Processing**: Data flows sequentially from one component to the next
- **Multiple Outputs**: A component can have multiple FLOW outputs to split or replicate data
- **Connector Attribute**: In JSON, identified by connector="FLOW" in metadata

**Behavior:**
- The source component generates or reads data
- Each row is passed to the connected component
- The target component receives and processes each row
- Schema must be compatible between connected components
- Data transformations occur as rows flow through the pipeline

**Usage in JSON Structure:**
When you see "connector": "FLOW" in a component's metadata section, it indicates that this component outputs or receives data through a FLOW connection. The metadata section will also define the schema (columns) for the data flowing through this connection.

**Common Patterns:**
- Input → Transformation → Output (e.g., tFileInputDelimited → tMap → tFileOutputDelimited)
- Multiple branches for different processing paths
- Data replication to multiple destinations
- Main flow with reject flow for error handling

**Example Use Cases:**
- Reading data from source and loading to target
- Transforming data through multiple processing steps
- Routing data to multiple destinations
- Implementing ETL data pipelines
""",
    "ITERATE": """
The ITERATE connection creates a loop where the target component is executed once for each iteration triggered by the source component. Unlike FLOW connections, ITERATE does not transfer data rows - instead, it triggers repeated execution.

**Characteristics:**
- **No Data Transfer**: Does not pass data rows; only triggers execution
- **Loop Control**: Each iteration executes the connected subjob once
- **Global Variables**: Data from iterations is accessed via global variables (globalMap)
- **Sequential Execution**: Iterations occur sequentially, one after another
- **Component Support**: Commonly used with tFileList, tFlowToIterate, loop components

**Behavior:**
- Source component determines the number of iterations (e.g., number of files, rows)
- For each iteration, the target component (and its subjob) executes once
- Values specific to each iteration are stored in global variables
- Iterations are sequential - one completes before the next begins

**Common Source Components for ITERATE:**
- tFileList: Iterates once per file found
- tFlowToIterate: Converts data rows to iterations
- tLoop: Iterates a specified number of times
- tFileInputDelimited (with iterate): Iterates once per row

**Global Variable Pattern:**
When a component generates ITERATE connections, it typically creates global variables that can be accessed using expressions like:
- ((String)globalMap.get("tFileList_1_CURRENT_FILE"))
- ((String)globalMap.get("tFileList_1_CURRENT_FILEPATH"))
- ((Integer)globalMap.get("tFileList_1_CURRENT_FILEDIRECTORY"))

**Example Use Cases:**
- Processing multiple files in a directory (tFileList → tFileInputDelimited)
- Calling a child job for each row of data (tFlowToIterate → tRunJob)
- Executing operations N times (tLoop → processing components)
- Dynamic job execution based on lookup data
""",
    "LOOKUP": """
The LOOKUP connection (also called Ref Row or Reference Row) is used in tMap components to bring in reference data for lookups and joins. The lookup flow is loaded into memory and used to enrich or validate the main data flow.

**Characteristics:**
- **Reference Data**: Provides reference/lookup data to tMap
- **Memory Loading**: Lookup data is loaded into memory for fast access
- **Join Operations**: Used for joining main flow with reference data
- **Multiple Lookups**: tMap can have multiple lookup connections
- **Load Strategies**: Different loading modes affect performance and behavior

**Load Modes (lookupMode attribute in JSON):**
- **LOAD_ONCE**: Loads the entire lookup dataset once at the beginning
  - Most efficient for static reference data
  - All lookup data remains in memory
  - Use when lookup data doesn't change during job execution

- **RELOAD_AT_EACH_ROW**: Reloads lookup data for every main flow row
  - Used when lookup data changes dynamically
  - Higher overhead but ensures fresh data
  - Necessary for complex dynamic lookups

- **CACHED**: Uses caching mechanism for lookup data
  - Balance between performance and memory
  - Caches frequently accessed lookup records

**Matching Modes (matchingMode attribute in JSON):**
- **UNIQUE_MATCH**: Expects exactly one match; error if multiple found
- **FIRST_MATCH**: Uses the first matching record found
- **ALL_MATCHES**: Returns all matching records (creates multiple output rows)

**Behavior:**
- Lookup flow is loaded according to specified load mode
- Main flow rows are processed sequentially
- For each main row, lookup is performed based on join keys
- Matched lookup data enriches the main row
- Non-matched rows can be handled based on join type (inner/outer)

**Example Use Cases:**
- Enriching transactions with customer details
- Adding product information to order lines
- Validating codes against reference tables
- Currency or rate lookups for calculations
- Joining multiple data sources in tMap
""",
    "REJECT": """
The REJECT connection outputs rows that fail validation, filtering, or processing rules in various components. It provides a separate data flow for handling "bad" or non-conforming data.

**Characteristics:**
- **Error Handling**: Captures rows that don't meet specified criteria
- **Separate Flow**: Creates an independent flow from main/accepted data
- **Schema Preservation**: Typically maintains the same schema as input
- **Optional Error Info**: May include additional error description columns
- **Component Support**: Supported by tMap, tFilterRow, tSchemaComplianceCheck, etc.

**Components with REJECT Connections:**
- **tMap**: Rejects rows that don't match join conditions or fail filter expressions
- **tFilterRow**: Outputs rows that don't meet filter conditions
- **tSchemaComplianceCheck**: Rejects rows with schema violations
- **tUniqRow**: Can output duplicate rows as rejects
- **tFileInputDelimited**: Can reject malformed rows

**Behavior:**
- Main processing continues normally for accepted rows
- Rejected rows are routed to the REJECT connection
- Reject flow can be processed separately (logged, corrected, archived)
- Allows graceful handling of data quality issues without stopping the job

**JSON Representation:**
In tMap components, reject outputs may have connector attributes indicating reject flows, often with additional error message columns added to the schema.

**Example Use Cases:**
- Logging invalid records for review
- Routing rejected data to error tables
- Separating good and bad data for different processing
- Data quality reporting and analysis
- Implementing data validation workflows with error handling
""",
    "RUN_IF": """
The RUN_IF connection is a conditional trigger that executes the target component only if a specified condition evaluates to true. It enables conditional workflow logic within Talend jobs.

**Characteristics:**
- **Conditional Execution**: Target executes only when condition is true
- **Boolean Expression**: Condition is a Java boolean expression
- **No Data Transfer**: Only controls execution flow, doesn't pass data
- **Runtime Evaluation**: Condition evaluated at runtime based on job state
- **Decision Logic**: Implements if-then logic in job orchestration

**Behavior:**
- Source component completes execution
- RUN_IF condition is evaluated
- If condition is true, target component executes
- If condition is false, target component is skipped
- Job continues with next components in the flow

**Condition Expressions:**
Conditions typically use global variables, context variables, or component statistics:
- ((Integer)globalMap.get("tFileInputDelimited_1_NB_LINE")) > 0
- context.environment.equals("PRODUCTION")
- ((String)globalMap.get("tRunJob_1_EXIT_CODE")).equals("0")
- ((Boolean)globalMap.get("tFileExist_1_EXISTS")) == true

**Common Patterns:**
- Execute component only if file exists
- Run cleanup only if processing succeeded
- Conditional notifications based on row counts
- Environment-specific processing logic
- Dynamic workflow based on previous component results

**Example Use Cases:**
- Send alert email only if error count > 0
- Load data only if source file is not empty
- Execute cleanup only on successful processing
- Conditional execution based on business rules
- Dynamic branching in complex workflows
""",
    "COMPONENT_OK": """
The COMPONENT_OK connection (also called OnComponentOk trigger) executes the target component after the source component completes successfully, regardless of the data processed.

**Characteristics:**
- **Success Trigger**: Fires only when source component completes without errors
- **No Data Transfer**: Control flow only, no data passed
- **Component-Level**: Triggers based on individual component completion
- **Sequential**: Ensures ordered execution of components
- **Error Handling**: Paired with COMPONENT_ERROR for complete flow control

**Behavior:**
- Source component executes and processes all data
- If no errors occurred, COMPONENT_OK trigger fires
- Target component then begins execution
- Useful for orchestrating component sequence
- Allows building complex dependency chains

**Common Patterns:**
- Step 1 → COMPONENT_OK → Step 2 → COMPONENT_OK → Step 3 (sequential processing)
- Parallel execution followed by synchronization
- Triggering post-processing after successful data operations
- Orchestrating database operations (load → COMPONENT_OK → commit)

**Difference from SUBJOB_OK:**
- COMPONENT_OK: Triggers after individual component completes
- SUBJOB_OK: Triggers after entire subjob (all connected components) completes

**Example Use Cases:**
- Execute database commit after successful data load
- Trigger file archiving after successful processing
- Start next processing step after completion of previous
- Orchestrate multi-step workflows
- Implementing sequential processing chains
""",
    "COMPONENT_ERROR": """
The COMPONENT_ERROR connection (also called OnComponentError trigger) executes the target component when the source component encounters an error during execution.

**Characteristics:**
- **Error Trigger**: Fires only when source component fails
- **No Data Transfer**: Control flow only, no data passed
- **Error Handling**: Enables error recovery and cleanup logic
- **Prevents Job Failure**: Can implement graceful error handling
- **Component-Level**: Responds to individual component errors

**Behavior:**
- Source component executes and encounters an error
- If error occurs, COMPONENT_ERROR trigger fires
- Target component executes error handling logic
- Can prevent job failure or implement recovery
- Error information available in global variables

**Error Information:**
Error details can be accessed via global variables:
- ((String)globalMap.get("tFileInputDelimited_1_ERROR_MESSAGE"))
- ((String)globalMap.get("tDBInput_1_ERROR_MESSAGE"))

**Common Patterns:**
- Component → COMPONENT_ERROR → tWarn (log error and continue)
- Component → COMPONENT_ERROR → tDie (stop job with custom error)
- Component → COMPONENT_ERROR → Error handling subjob
- Component → COMPONENT_ERROR → Notification component

**Example Use Cases:**
- Send error notification email when component fails
- Log errors to database or file for analysis
- Implement retry logic for transient failures
- Graceful degradation (use default values on error)
- Cleanup operations when processing fails
""",
    "SUBJOB_OK": """
The SUBJOB_OK connection (also called OnSubjobOk trigger) executes the target component after the entire source subjob completes successfully. A subjob includes the starting component and all components connected via data flows.

**Characteristics:**
- **Subjob-Level Trigger**: Fires after entire subjob completes, not just one component
- **Success Condition**: All components in subjob must complete without errors
- **No Data Transfer**: Control flow only
- **Job Orchestration**: Primary mechanism for sequencing subjobs
- **Common Pattern**: Most common trigger for job flow control

**Subjob Definition:**
A subjob consists of:
- A starting component (often with green background in designer)
- All components connected via FLOW, ITERATE, or other data connections
- Ends when no more connected components remain

**Behavior:**
- Entire source subjob executes (all connected components)
- If all components complete successfully, SUBJOB_OK trigger fires
- Target component (starting new subjob) then executes
- Provides clean separation between processing phases

**Common Patterns:**
- Subjob 1 → SUBJOB_OK → Subjob 2 → SUBJOB_OK → Subjob 3 (sequential subjobs)
- Used in tPrejob → SUBJOB_OK → Main Processing → SUBJOB_OK → tPostjob
- Data Extraction subjob → SUBJOB_OK → Transformation subjob → SUBJOB_OK → Load subjob

**Difference from COMPONENT_OK:**
- SUBJOB_OK: Waits for all connected components in subjob to complete
- COMPONENT_OK: Triggers immediately after single component completes

**Example Use Cases:**
- Execute ETL phases in sequence (Extract → Transform → Load)
- Start processing only after initialization completes
- Trigger cleanup after all data processing finishes
- Orchestrate complex multi-phase workflows
- Ensure prerequisites complete before starting dependent processing
""",
    "SUBJOB_ERROR": """
The SUBJOB_ERROR connection (also called OnSubjobError trigger) executes the target component when any component in the source subjob encounters an error.

**Characteristics:**
- **Subjob-Level Error Handling**: Triggers if any component in subjob fails
- **No Data Transfer**: Control flow only
- **Centralized Error Handling**: Single error handler for entire subjob
- **Prevents Job Failure**: Can implement graceful error handling for subjobs
- **Paired with SUBJOB_OK**: Implements if-success/if-error logic

**Behavior:**
- Source subjob executes
- If any component encounters an error, SUBJOB_ERROR trigger fires
- Target component executes error handling logic
- Remaining components in source subjob may not execute (depends on error)

**Common Patterns:**
- Subjob → SUBJOB_ERROR → Error logging component
- Subjob → SUBJOB_ERROR → tSendMail (error notification)
- Subjob → SUBJOB_ERROR → tDBRollback (rollback transaction on error)
- Parallel paths: Subjob → SUBJOB_OK → Success path, Subjob → SUBJOB_ERROR → Error path

**Example Use Cases:**
- Send email notification when ETL phase fails
- Rollback database transactions on processing errors
- Log errors to monitoring system
- Execute cleanup logic when processing fails
- Implement recovery procedures for failed subjobs
""",
    "PARALLELIZE": """
The PARALLELIZE connection enables parallel execution of multiple subjobs, allowing them to run simultaneously instead of sequentially.

**Characteristics:**
- **Parallel Execution**: Multiple subjobs execute at the same time
- **Performance Optimization**: Reduces total job execution time
- **Independent Subjobs**: Connected subjobs should be independent (no dependencies)
- **Resource Usage**: May increase CPU and memory usage
- **Thread-Based**: Each parallel subjob runs in separate thread

**Behavior:**
- Source component triggers parallel execution
- All components connected via PARALLELIZE start simultaneously
- Job waits for all parallel subjobs to complete before continuing
- Useful for processing independent data sources concurrently

**Common Patterns:**
- Single trigger → PARALLELIZE → Multiple independent processing subjobs
- Processing multiple files simultaneously
- Parallel data extraction from different sources
- Concurrent API calls or web service requests

**Considerations:**
- Ensure parallel subjobs don't compete for same resources (files, database connections)
- Be aware of thread safety issues
- Monitor resource usage (CPU, memory, database connections)
- Use appropriate thread pool settings

**Example Use Cases:**
- Extract data from multiple source systems simultaneously
- Process multiple files concurrently
- Parallel API calls for faster data retrieval
- Independent transformation processes running in parallel
- Load data to multiple targets simultaneously
""",
    "SYNCHRONIZE": """
The SYNCHRONIZE connection waits for multiple parallel subjobs to complete before proceeding. It acts as a synchronization point for parallel execution paths.

**Characteristics:**
- **Synchronization Point**: Waits for all input subjobs to finish
- **Parallel to Sequential**: Converts parallel execution back to sequential
- **No Data Transfer**: Control flow only
- **Multiple Inputs**: Can have multiple incoming SYNCHRONIZE connections
- **Continuation**: Proceeds only when all parallel paths complete

**Behavior:**
- Multiple subjobs execute in parallel
- Each completes at different times
- SYNCHRONIZE waits for all to finish
- Once all complete, target component executes
- Ensures all parallel work is done before continuing

**Common Patterns:**
- Parallel processing → SYNCHRONIZE → Aggregation or reporting
- Multiple extracts → SYNCHRONIZE → Single load process
- Fork-Join pattern (split work, process in parallel, join results)

**Example Use Cases:**
- Wait for all parallel file processing to complete before generating summary report
- Ensure all data sources are extracted before starting transformation
- Synchronize multiple parallel loads before final validation
- Coordinate parallel API calls before processing combined results
""",
    "RUN_AFTER": """
The RUN_AFTER connection executes the target component after the source component completes, regardless of success or failure. Unlike COMPONENT_OK, it always triggers.

**Characteristics:**
- **Unconditional Execution**: Triggers regardless of source component result
- **No Data Transfer**: Control flow only
- **Always Executes**: Runs even if source component fails
- **Cleanup Pattern**: Commonly used for cleanup operations
- **Simple Sequencing**: Ensures execution order without conditions

**Behavior:**
- Source component executes (success or failure)
- When source completes, RUN_AFTER trigger fires
- Target component executes regardless of source outcome
- Useful for ensuring certain operations always occur

**Difference from Other Triggers:**
- COMPONENT_OK: Only on success
- COMPONENT_ERROR: Only on error
- RUN_AFTER: Always, regardless of result

**Example Use Cases:**
- Close file or database connection regardless of processing result
- Log execution completion (success or failure)
- Cleanup temporary files after processing
- Final notification regardless of job outcome
- Ensuring resources are released
""",
    "ROUTE": """
The ROUTE connection is used with web service and ESB components to route messages based on content or conditions.

**Characteristics:**
- **Message Routing**: Routes messages in ESB/integration scenarios
- **Content-Based**: Routing decisions based on message content
- **Multiple Routes**: Can have multiple ROUTE outputs with different conditions
- **ESB Pattern**: Implements content-based router pattern
- **XML/SOAP Context**: Commonly used with web service components

**Behavior:**
- Source component receives or generates message
- Routing conditions are evaluated
- Message is routed to appropriate target based on conditions
- Multiple targets possible based on different routing rules

**Common Components:**
- tRouteInput / tRouteOutput: Define routes in ESB jobs
- tESBConsumer / tESBProvider: Web service endpoints
- Message routing based on XML content or headers

**Example Use Cases:**
- Route web service requests to different processors based on message type
- Content-based routing in integration scenarios
- Implementing message routing patterns
- Service orchestration based on request content
""",
    "ROWMAIN": """
The ROWMAIN connection is an alias or alternate name for the main FLOW connection in some Talend components and contexts. It functions identically to FLOW.

**Characteristics:**
- **Same as FLOW**: Represents main data flow
- **Naming Variant**: Alternative terminology in some component contexts
- **Data Transfer**: Transfers rows between components
- **Schema Propagation**: Passes schema definitions

**Usage:**
Functionally equivalent to FLOW connection. You may see "ROWMAIN" in some component definitions or older Talend versions, but it behaves the same as FLOW.

**Example Use Cases:**
Same as FLOW connection - used for main data flow between components.
""",
    "TABLE": """
The TABLE connection is used in specific Talend components that work with table-based or dataset-based processing, particularly in components dealing with multiple tables or database operations.

**Characteristics:**
- **Table-Level Operations**: Operates on entire tables rather than rows
- **Metadata Focus**: Often carries table metadata rather than row data
- **Specialized Components**: Used by specific database or table manipulation components
- **Schema Definition**: Carries table structure information

**Common Contexts:**
- Components performing table-level operations
- Database comparison or synchronization components
- Metadata-driven processing

**Example Use Cases:**
- Table comparison operations
- Database schema migration
- Bulk table operations
- Metadata-driven processing workflows
""",
    "INPUT": """
The INPUT connection represents an input data flow in certain specialized Talend components, particularly in custom or advanced components.

**Characteristics:**
- **Input Designation**: Explicitly marks input data flow
- **Component-Specific**: Used in components with multiple types of connections
- **Data Reception**: Receives data from upstream components
- **Schema-Based**: Carries schema and data

**Usage:**
Typically seen in advanced components that need to distinguish between different types of inputs or in custom component development.

**Example Use Cases:**
- Custom component development
- Advanced transformation components with multiple input types
- Specialized data processing components
""",
    "OUTPUT": """
The OUTPUT connection represents an output data flow in certain specialized Talend components, explicitly marking the data output from a component.

**Characteristics:**
- **Output Designation**: Explicitly marks output data flow
- **Component-Specific**: Used in components with multiple types of connections
- **Data Transmission**: Sends data to downstream components
- **Schema-Based**: Carries schema and data

**Usage:**
Typically seen in advanced components that need to distinguish between different types of outputs or in custom component development.

**Example Use Cases:**
- Custom component development
- Advanced transformation components with multiple output types
- Specialized data processing components
""",
}
