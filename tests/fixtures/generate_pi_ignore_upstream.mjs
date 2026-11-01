// Compare native matcher with the actual dependency used by pinned skills.ts.
import fs from "node:fs";
import ignore from "ignore";
const cases = [
  {name:"negation-and-parents",files:{".gitignore":"*.tmp\n!keep.tmp\nbuild/\n!build/keep.md\n"},paths:["a.tmp","keep.tmp","deep/a.tmp","deep/keep.tmp","build/keep.md","deep/build/keep.md","note.md"]},
  {name:"globstar",files:{".ignore":"**/cache/**\nsrc/**/test?.md\nroot/*.md\n"},paths:["cache/a.md","deep/cache/a.md","src/test1.md","src/lib/test2.md","root/a.md","root/nested/a.md","src/a.md"]},
  {name:"nested-prefix",files:{"nested/.fdignore":"hidden.md\n!visible.md\n"},paths:["hidden.md","nested/hidden.md","nested/deep/hidden.md","nested/visible.md"]},
  {name:"escaping-and-case",files:{".gitignore":"\\#literal.md\n\\!literal.md\nUPPER.md\nfile[0-9].md\n"},paths:["#literal.md","!literal.md","upper.md","file1.md","filex.md"]},
  {name:"root-slash-skills",files:{".gitignore":"/hidden/\n"},paths:["hidden/a.md","nested/hidden/a.md","other/a.md"]},
];
for (const c of cases) {
 const ig=ignore();
 for (const [filename,content] of Object.entries(c.files)) {
  const prefix=filename.includes("/")?filename.slice(0,filename.lastIndexOf("/")+1):"";
  // Verbatim prefixIgnorePattern behavior from pinned core/skills.ts:24-45.
  for(const line of content.split(/\r?\n/)) {
   const trimmed=line.trim();if(!trimmed)continue;if(trimmed.startsWith("#")&&!trimmed.startsWith("\\#"))continue;
   let pattern=line,negated=false;
   if(pattern.startsWith("!")){negated=true;pattern=pattern.slice(1);}else if(pattern.startsWith("\\!")){pattern=pattern.slice(1);}
   if(pattern.startsWith("/"))pattern=pattern.slice(1);
   const prefixed=prefix?`${prefix}${pattern}`:pattern;ig.add(negated?`!${prefixed}`:prefixed);
  }
 }
 c.expected=Object.fromEntries(c.paths.map(p=>[p,ig.ignores(p)]));
}
fs.writeFileSync("tests/fixtures/pi_ignore_upstream.json",JSON.stringify({baseline:"Pi 1.4.0 skills.ts prefixIgnorePattern + original npm ignore dependency",cases},null,2)+"\n");
