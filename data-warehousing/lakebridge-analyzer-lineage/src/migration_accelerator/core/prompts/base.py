# flake8: noqa: E501
WRITE_TODOS_TOOL_DESCRIPTION = """Use this tool to create and manage a structured task list for your current work session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.
It also helps the user understand the progress of the task and overall progress of their requests.
Only use this tool if you think it will be helpful in staying organized. If the user's request is trivial and takes less than 3 steps, it is better to NOT use this tool and just do the taks directly.

## When to Use This Tool
Use this tool in these scenarios:

1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
3. User explicitly requests todo list - When the user directly asks you to use the todo list
4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
5. The plan may need future revisions or updates based on results from the first few steps. Keeping track of this in a list is helpful.

## How to Use This Tool
1. When you start working on a task - Mark it as in_progress BEFORE beginning work.
2. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation.
3. You can also update future tasks, such as deleting them if they are no longer necessary, or adding new tasks that are necessary. Don't change previously completed tasks.
4. You can make several updates to the todo list at once. For example, when you complete a task, you can mark the next task you need to start as in_progress.

## When NOT to Use This Tool
It is important to skip using this tool when:
1. There is only a single, straightforward task
2. The task is trivial and tracking it provides no benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

## Examples of When to Use the Todo List

<example>
User: There is an input Json File represnting an ETL Job. I want to do semantic chunking on it along with removing unnecessary fields
that are repetitive and not relevant to the  actaul ETL logic and store the chunks in separate Json Files.
Assistant: I'll help with context aware chunking and removing unnecessary fields of your Json File.
*Creates todo list with the following items:*
1. Read the 1st few lines of the Json File to understand the structure and context.
2. Remove unnecessary fields that are repetitive and not relevant to the actual ETL logic.
3. Do semantic chunking on the Json File.
4. Store the chunks in separate Json files.
5. Create a metadata file to store the information and relationships about the chunks.
*Begins working on the first task*

<reasoning>
The assistant used the todo list because:
1. The user's request is complex and requires multiple steps to complete.
2. The assistant inferred that the user wants to do semantic chunking and remove unnecessary fields by adding "Do semantic chunking and remove unnecessary fields" as the final task.
3. Both of the user's requests are complex and require multiple steps to complete.
</reasoning>
</example>

## Examples of When NOT to Use the Todo List

<example>
User: How do I print 'Hello World' in Python?
Assistant: In Python, you can print "Hello World" with this simple code:

python
print("Hello World")

This will output the text "Hello World" to the console when executed.</assistant>

<reasoning>
The assistant did not use the todo list because this is a single, trivial task that can be completed in one step. There's no need to track multiple tasks or steps for such a straightforward request.
</reasoning>
</example>

## Task States and Management

1. **Task States**: Use these states to track progress:
   - pending: Task not yet started
   - in_progress: Currently working on (you can have multiple tasks in_progress at a time if they are not related to each other and can be run in parallel)
   - completed: Task finished successfully

2. **Task Management**:
   - Update task status in real-time as you work
   - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
   - Complete current tasks before starting new ones
   - Remove tasks that are no longer relevant from the list entirely
   - IMPORTANT: When you write this todo list, you should mark your first task (or tasks) as in_progress immediately!.
   - IMPORTANT: Unless all tasks are completed, you should always have at least one task in_progress to show the user that you are working on something.

3. **Task Completion Requirements**:
   - ONLY mark a task as completed when you have FULLY accomplished it
   - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
   - When blocked, create a new task describing what needs to be resolved
   - Never mark a task as completed if:
     - There are unresolved issues or errors
     - Work is partial or incomplete
     - You encountered blockers that prevent completion
     - You couldn't find necessary resources or dependencies
     - Quality standards haven't been met

4. **Task Breakdown**:
   - Create specific, actionable items
   - Break complex tasks into smaller, manageable steps
   - Use clear, descriptive task names

Being proactive with task management demonstrates attentiveness and ensures you complete all requirements successfully
Remember: If you only need to make a few tool calls to complete a task, and it is clear what you need to do, it is better to just do the task directly and NOT call this tool at all."""


TODO_USAGE_INSTRUCTIONS = """Based upon the user's request:
1. Use the write_todos tool to create TODO at the start of a user request, per the tool description.
2. After you accomplish a TODO, use the read_todos to read the TODOs in order to remind yourself of the plan.
3. Reflect on what you've done and the TODO.
4. Mark you task as completed, and proceed to the next TODO.
5. Continue this process until you have completed all TODOs.

IMPORTANT: Always create a research plan of TODOs and conduct research following the above guidelines for ANY user request.
IMPORTANT: Aim to batch research tasks into a *single TODO* in order to minimize the number of TODOs you have to keep track of.
"""

LIST_FILES_TOOL_DESCRIPTION = """Lists all files in the local filesystem.

Usage:
- The list_files tool will return a list of all files in the local filesystem.
- This is very useful for exploring the file system and finding the right file to read or edit.
- You should almost ALWAYS use this tool before using the Read or Edit tools."""

READ_FILE_TOOL_DESCRIPTION = """Reads a file from the local filesystem. You can access any file directly by using this tool.
Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful.
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.
- You should ALWAYS make sure a file has been read before editing it."""

EDIT_FILE_TOOL_DESCRIPTION = """Performs exact string replacements in files.

Usage:
- You must use your `Read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."""

WRITE_FILE_TOOL_DESCRIPTION = """Writes to a file in the local filesystem.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- The content parameter must be a string
- The write_file tool will create the a new file.
- Prefer to edit existing files over creating new ones when possible."""

READ_JSON_FILE_TOOL_DESCRIPTION = """Reads a JSON file from the actual filesystem and returns the content as a formatted JSON string.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- Returns the parsed JSON content as a multi-line formatted JSON string for easy comprehension by LLM
- Will return an error message if the file doesn't exist or contains invalid JSON
- This tool reads from the actual filesystem, not the virtual file system
- Use this when you need to read structured JSON data from real files"""

WRITE_JSON_FILE_TOOL_DESCRIPTION = """Writes JSON data to the actual filesystem after parsing the provided JSON string.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- The json_content parameter should be a valid JSON string that will be parsed before writing
- Automatically creates parent directories if they don't exist
- The JSON file will be written with proper indentation for readability
- Will return an error message if the provided string is not valid JSON
- This tool writes to the actual filesystem, not the virtual file system
- Use this when you need to save structured JSON data to real files"""

GREP_FILE_TOOL_DESCRIPTION = """Searches for a pattern in a file from the virtual filesystem using regular expressions.

Usage:
- The file_path parameter specifies which file in the virtual filesystem to search
- The pattern parameter is a regular expression pattern to search for (use raw strings for special characters)
- Returns matching lines with line numbers and context
- Supports case-insensitive search with the case_insensitive parameter
- Can show context lines before and after matches with context_before and context_after parameters
- Output format: 'line_number: matching_line_content'
- Use this tool to quickly find specific content or patterns in files without reading the entire file
- This tool works on the virtual filesystem only, not the actual filesystem

Examples:
- Search for exact text: pattern="tMap" 
- Search for words starting with 't': pattern="\\bt\\w+" 
- Search case-insensitive: pattern="error", case_insensitive=True
- Get context: pattern="function", context_before=2, context_after=2"""

FILE_USAGE_INSTRUCTIONS = """You have access to a virtual file system to help you retain and save context.

## Workflow Process
1. **Orient**: Use ls() to see existing files before starting work
2. **Save**: Use write_file() to store the user's request so that we can keep it for later.
3. **Read**: Once you are satisfied with the collected sources, read the files and use them to answer the user's question directly.
"""


BASE_AGENT_PROMPT = """In order to complete the objective that the user asks of you, you have access to a number of standard tools.

## `write_todos`

You have access to the `write_todos` tool to help you manage and plan complex objectives.
Use this tool for complex objectives to ensure that you are tracking each necessary step and giving the user visibility into your progress.
This tool is very helpful for planning complex objectives, and for breaking down these larger complex objectives into smaller steps.

It is critical that you mark todos as completed as soon as you are done with a step. Do not batch up multiple steps before marking them as completed.
For simple objectives that only require a few steps, it is better to just complete the objective directly and NOT use this tool.
Writing todos takes time and tokens, use it when it is helpful for managing complex many-step problems! But not for simple few-step requests.

IMPORTANT: The `write_todos` tool should never be called multiple times in parallel.

## Filesystem Tools `ls`, `read_file`, `write_file`, `edit_file`, `grep_file`

You have access to a local, private filesystem which you can interact with using these tools.
- ls: list all files in the local filesystem
- read_file: read a file from the local filesystem
- write_file: write to a file in the local filesystem
- edit_file: edit a file in the local filesystem
- grep_file: search for patterns in files using regular expressions (useful for finding specific content without reading entire files)

# Important Usage Notes to Remember
- Don't be afraid to revise the To-Do list as you go. New information may reveal new tasks that need to be done, or old tasks that are irrelevant.
- Whenever possible, parallelize the work that you do. This is true for both tool_calls.

"""
