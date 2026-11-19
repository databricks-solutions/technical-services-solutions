# UTF-16 → UTF-8 conversion

Convert exported legacy code (SQL scripts, SSIS packages, other XML exports) from **UTF-16** to **UTF-8** before you analyse or convert it with Lakebridge or Genie Migrate.

## Why

Lakebridge and Genie Migrate work best with source files in **UTF-8 or ANSI**. Converting UTF-16 ("Unicode") exports first gives you consistent, predictable results across the tools.

UTF-16 is common in Windows exports:

- **SSMS → Tasks → Generate Scripts** saves as *Unicode text* (UTF-16) by default.
- Some SSIS packages and other XML exports declare `encoding="utf-16"`.

To avoid the problem at the source, set **Save as: ANSI text** in the SSMS *Set Scripting Options* page. For files you already exported, use the commands below.

## Check whether your files are UTF-16

- **macOS / Linux:** `file --mime-encoding *.sql`. UTF-16 files show `utf-16le` or `utf-16be`.
- **Windows PowerShell:** files that start with the bytes `FF FE` or `FE FF` are UTF-16:
  ```powershell
  Get-ChildItem *.sql | Where-Object { $b = [IO.File]::ReadAllBytes($_.FullName); $b.Length -ge 2 -and (($b[0] -eq 0xFF -and $b[1] -eq 0xFE) -or ($b[0] -eq 0xFE -and $b[1] -eq 0xFF)) } | Select-Object Name
  ```

## Convert a single file

**macOS / Linux**

```bash
iconv -f UTF-16 -t UTF-8 in.sql > out.sql
```

**Windows PowerShell 5.1 or 7** (run from the folder that holds the file):

```powershell
[IO.File]::WriteAllText("$PWD\out.sql", [IO.File]::ReadAllText("$PWD\in.sql"), (New-Object Text.UTF8Encoding $false))
```

- No extra encoding flags are needed: `ReadAllText` detects UTF-16 from the BOM, and `UTF8Encoding $false` writes UTF-8 without a BOM.
- For a UTF-16 file **without** a BOM, use `ReadAllText("$PWD\in.sql", [Text.Encoding]::Unicode)`.
- Write to a **new** file and keep the `$PWD\` prefix: .NET does not resolve relative paths against the PowerShell current folder.
- Do **not** use `Get-Content f.sql | Set-Content -Encoding utf8 f.sql`. It fails on the same file ("file is in use"), and in PowerShell 5.1 `-Encoding utf8` adds a BOM.
- For an XML file, also change `encoding="utf-16"` to `encoding="utf-8"` in the first line. The bulk scripts do this for you.

## Convert a whole export folder

| Script | Platform |
|---|---|
| [`to_utf8.sh`](to_utf8.sh) | macOS, Linux (needs `bash`, `file`, `iconv`, `perl`; all preinstalled on most systems) |
| [`To-Utf8.ps1`](To-Utf8.ps1) | Windows PowerShell 5.1 or PowerShell 7 |

**macOS / Linux**

```bash
./to_utf8.sh <source_dir> <output_dir>
```

**Windows**

```powershell
.\To-Utf8.ps1 -Src C:\export -Out C:\export_utf8
```

Then upload or analyse the **output** folder.

### What the scripts do

- Walk the source folder recursively and write a **converted copy** to the output folder, keeping the subfolder structure. **Source files are never modified.**
- Convert only files that start with a **UTF-16 BOM** (little- or big-endian), which is what SSMS and most Windows tools write. All other files are copied unchanged.
- In XML exports (`.dtsx`, `.xml`, …), rewrite the declaration `encoding="utf-16"` to `encoding="utf-8"` so the file stays valid XML.
- Write UTF-8 **without** a BOM, and keep line endings as exported (SSMS writes CRLF).
- Skip hidden files and folders (for example `.DS_Store`, `.git`) and the output folder itself.
- Print a summary at the end. The bash script also lists any UTF-16 files left in the output (expected: none).

### Good practice

- Put the output folder **outside** the source folder. If it is inside, it is skipped, but any other folder inside the source (for example, the output of an earlier run) is copied as well.
- Check that the summary count matches the number of files you exported.

### If PowerShell blocks the script

Windows may refuse to run a downloaded script ("running scripts is disabled on this system" or "is not digitally signed"). Options, if your security policy allows them:

- Unblock the downloaded file once: `Unblock-File .\To-Utf8.ps1`.
- Or run it once with the policy bypassed for that process only:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\To-Utf8.ps1 -Src C:\export -Out C:\export_utf8
  ```

If your organisation enforces an execution policy through **Group Policy**, `-ExecutionPolicy Bypass` has no effect. Ask your administrator, or use the single-file PowerShell command above, which needs no script file.

## Limitations

- UTF-16 files **without** a BOM are not detected and are copied unchanged. They are rare; convert them with the single-file command.
- The XML declaration is rewritten only when it uses double quotes (`encoding="utf-16"`) on the first line.
- Files are converted as a whole in memory. Very large single files (hundreds of MB) need enough RAM.

## Tested

- **macOS:** 176 SQL Server objects exported by SSMS as UTF-16LE; UTF-16BE files; an SSIS project (`.dtsx`, `.conmgr`, `.params`, `.database`) saved as UTF-16LE with `encoding="utf-16"`. All converted, no BOM, no UTF-16 left, text identical to the source, and XML well-formed and canonically identical to the original.
- **Windows Server 2022, PowerShell 5.1:** the same SQL files plus UTF-16BE, a UTF-16 `.dtsx`, an ASCII file, hidden files, and an output folder inside the source. All correct.
