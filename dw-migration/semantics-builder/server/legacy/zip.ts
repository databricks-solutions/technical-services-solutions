import { inflateRawSync } from 'node:zlib';

const MAX_ENTRIES = 2000;
const MAX_FILE_BYTES = 30_000_000;

/**
 * Reads one file from a zip archive in memory, such as DataModelSchema in a Power BI template. Nothing is written to
 * disk, so entry paths cannot escape a folder. The size limit stops a zip bomb: inflate stops at MAX_FILE_BYTES.
 */
export function readZipEntry(zip: Buffer, wanted: (name: string) => boolean): Buffer | null {
  // The end of central directory record is in the last 64 KB + 22 bytes.
  let eocd = -1;
  for (let i = zip.length - 22; i >= Math.max(0, zip.length - 65_558); i--)
    if (zip.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  if (eocd < 0) throw new Error('The file is not a zip archive.');
  const entries = zip.readUInt16LE(eocd + 10);
  if (entries > MAX_ENTRIES) throw new Error('The archive has too many files.');
  let p = zip.readUInt32LE(eocd + 16);
  for (let n = 0; n < entries; n++) {
    if (p + 46 > zip.length || zip.readUInt32LE(p) !== 0x02014b50) throw new Error('The zip directory is broken.');
    const method = zip.readUInt16LE(p + 10);
    const compressed = zip.readUInt32LE(p + 20);
    const size = zip.readUInt32LE(p + 24);
    const nameLen = zip.readUInt16LE(p + 28);
    const extraLen = zip.readUInt16LE(p + 30);
    const commentLen = zip.readUInt16LE(p + 32);
    const local = zip.readUInt32LE(p + 42);
    const name = zip.toString('utf8', p + 46, p + 46 + nameLen);
    p += 46 + nameLen + extraLen + commentLen;
    if (!wanted(name)) continue;
    if (size > MAX_FILE_BYTES) throw new Error(`${name} is larger than ${MAX_FILE_BYTES / 1_000_000} MB.`);
    if (local + 30 > zip.length || zip.readUInt32LE(local) !== 0x04034b50) throw new Error('The zip entry is broken.');
    const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
    const data = zip.subarray(start, start + compressed);
    if (method === 0) return Buffer.from(data);
    if (method === 8) return inflateRawSync(data, { maxOutputLength: MAX_FILE_BYTES });
    throw new Error(`${name} uses a zip compression that is not supported.`);
  }
  return null;
}
