import fs from "node:fs";
import vm from "node:vm";

const source=fs.readFileSync(new URL("../static/companion.js",import.meta.url),"utf8");
const html=fs.readFileSync(new URL("../static/companion.html",import.meta.url),"utf8");
const css=fs.readFileSync(new URL("../static/companion.css",import.meta.url),"utf8");

for(const contract of ["/library","/import/url","/import/file","/jobs/","/evidence/","/media/audio"]){
  if(!source.includes(contract))throw new Error(`missing Companion flow: ${contract}`);
}
for(const contract of ["X-CSRF-Token","credentials:\"same-origin\"","XMLHttpRequest","xhr.upload.onprogress"]){
  if(!source.includes(contract))throw new Error(`missing frontend security/progress contract: ${contract}`);
}
if(html.includes("/static/app.js"))throw new Error("Companion must not load desktop app.js");
if(!html.includes('name="viewport"')||!css.includes("@media(max-width:390px)"))throw new Error("390px mobile contract missing");
if(!source.includes("COPY={zh:")||!source.includes(",en:"))throw new Error("bilingual copy missing");
if(css.includes("min-width:390px"))throw new Error("horizontal overflow floor detected");
console.log("companion frontend: mobile, bilingual, progress and API boundaries passed");
