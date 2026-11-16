/**
 * A small, strict XML reader for Tableau files. It refuses DOCTYPE and entity declarations, so no external entity
 * or entity expansion attack is possible. It keeps elements, attributes and text; it ignores comments and
 * processing instructions.
 */
export interface XmlNode {
  tag: string;
  attrs: Record<string, string>;
  children: XmlNode[];
  text: string;
}

const MAX_NODES = 500_000;
const MAX_DEPTH = 200;
const NAMED: Record<string, string> = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };

const decode = (s: string) =>
  s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-z]+);/g, (all, e: string) => {
    if (e[0] !== '#') return NAMED[e] ?? all;
    const code = e[1] === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
    return Number.isFinite(code) && code <= 0x10ffff ? String.fromCodePoint(code) : all;
  });

export function parseXml(src: string): XmlNode {
  if (/<!DOCTYPE|<!ENTITY/i.test(src))
    throw new Error('The file has a DOCTYPE or an entity declaration, which is not allowed.');
  const root: XmlNode = { tag: '#root', attrs: {}, children: [], text: '' };
  const stack: XmlNode[] = [root];
  let i = 0;
  let count = 0;
  const fail = (why: string): never => {
    throw new Error(`The XML does not parse at line ${src.slice(0, i).split('\n').length}: ${why}`);
  };
  while (i < src.length) {
    const lt = src.indexOf('<', i);
    const top = stack[stack.length - 1];
    if (lt < 0) {
      top.text += decode(src.slice(i));
      break;
    }
    if (lt > i) top.text += decode(src.slice(i, lt));
    i = lt;
    if (src.startsWith('<!--', i)) {
      const end = src.indexOf('-->', i);
      if (end < 0) fail('a comment does not end');
      i = end + 3;
    } else if (src.startsWith('<![CDATA[', i)) {
      const end = src.indexOf(']]>', i);
      if (end < 0) fail('a CDATA section does not end');
      top.text += src.slice(i + 9, end);
      i = end + 3;
    } else if (src.startsWith('<?', i)) {
      const end = src.indexOf('?>', i);
      if (end < 0) fail('a processing instruction does not end');
      i = end + 2;
    } else if (src.startsWith('</', i)) {
      const end = src.indexOf('>', i);
      const tag = src.slice(i + 2, end).trim();
      if (end < 0 || stack.length < 2 || top.tag !== tag) fail(`</${tag}> does not match`);
      stack.pop();
      i = end + 1;
    } else {
      const m = /^<([A-Za-z_][\w.:-]*)/.exec(src.slice(i, i + 200));
      if (!m) fail('a tag name is missing');
      i += m![0].length;
      const node: XmlNode = { tag: m![1], attrs: {}, children: [], text: '' };
      if (++count > MAX_NODES) fail('it is too large');
      for (;;) {
        while (/\s/.test(src[i] ?? '')) i++;
        if (src[i] === '>' || src.startsWith('/>', i)) break;
        const a = /^([A-Za-z_][\w.:-]*)\s*=\s*("([^"]*)"|'([^']*)')/.exec(src.slice(i, i + 100_000));
        if (!a) fail(`an attribute of <${node.tag}> is broken`);
        node.attrs[a![1]] = decode(a![3] ?? a![4] ?? '');
        i += a![0].length;
      }
      top.children.push(node);
      if (src.startsWith('/>', i)) i += 2;
      else {
        i++;
        if (stack.length > MAX_DEPTH) fail('it is nested too deep');
        stack.push(node);
      }
    }
  }
  if (stack.length !== 1) fail(`<${stack[stack.length - 1].tag}> does not end`);
  return root;
}

/** All descendants with the tag, in document order. */
export function findAll(n: XmlNode, tag: string, out: XmlNode[] = []): XmlNode[] {
  for (const c of n.children) {
    if (c.tag === tag) out.push(c);
    findAll(c, tag, out);
  }
  return out;
}

export const child = (n: XmlNode, tag: string) => n.children.find((c) => c.tag === tag);
