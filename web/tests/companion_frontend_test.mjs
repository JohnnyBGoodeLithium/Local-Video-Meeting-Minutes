import fs from "node:fs";

const source=fs.readFileSync(new URL("../static/companion.js",import.meta.url),"utf8");
const state=fs.readFileSync(new URL("../static/companion-state.js",import.meta.url),"utf8");
const router=fs.readFileSync(new URL("../static/companion-router.js",import.meta.url),"utf8");
const html=fs.readFileSync(new URL("../static/companion.html",import.meta.url),"utf8");
const css=fs.readFileSync(new URL("../static/companion.css",import.meta.url),"utf8");
const frontend=source+state+router;

for(const contract of ["/library","/import/url","/import/file","/jobs/","/evidence/","/media/"]){
  if(!source.includes(contract))throw new Error(`missing Companion flow: ${contract}`);
}
for(const contract of ["X-CSRF-Token","credentials:\"same-origin\"","XMLHttpRequest","xhr.upload.onprogress"]){
  if(!source.includes(contract))throw new Error(`missing frontend security/progress contract: ${contract}`);
}
for(const contract of ["location.hash","history.replaceState","history[","sessionStorage","companion:tracked-jobs:v2"]){
  if(!frontend.includes(contract))throw new Error(`missing pairing-fragment/job-recovery contract: ${contract}`);
}
if(source.includes("location.search"))throw new Error("pairing token must come from the URL fragment, not the query string");
if(/Authorization|Bearer/i.test(source))throw new Error("Companion must not carry bearer tokens in the browser");
if(!state.includes(".map(({id, title}) => ({id, title}))"))throw new Error("tracked jobs must persist only id and safe title");
if(/async function pollTrackedJobs[\s\S]*?setRoute\(/.test(source.split("async function openJob")[0]))throw new Error("job polling must never control navigation");
if(html.includes("/static/app.js"))throw new Error("Companion must not load desktop app.js");
if(!html.includes('name="viewport"')||!css.includes("max-width:599px"))throw new Error("compact viewport contract missing");
if(!source.includes("COPY={zh:")||!source.includes(",en:"))throw new Error("bilingual copy missing");
if(css.includes("min-width:390px"))throw new Error("horizontal overflow floor detected");
if(!html.includes('id="video-file"')||!html.includes('accept="video/*"'))throw new Error("iOS Photo Library video picker missing");
if(!source.includes('$("video-file")'))throw new Error("video picker must be wired to uploadFile");
if(!source.includes('/library?limit=5')||!source.includes('limit:"20"'))throw new Error("Home/library paging limits missing");
if(!html.includes('id="send-dialog"')||!source.includes('.showModal()'))throw new Error("single Send action dialog missing");
for(const contract of ['role="tablist"','data-tab="overview"','data-tab="chapters"','data-tab="people"','data-tab="transcript"'])if(!html.includes(contract))throw new Error(`adaptive review tab missing: ${contract}`);
if(!source.includes('limit:"50"')||!source.includes('ArrowRight')||!source.includes('ArrowLeft'))throw new Error("transcript paging or tab keyboard contract missing");
if(!html.includes('id="video-player"')||!html.includes('id="audio-player"')||!source.includes('captions/${mode}.vtt'))throw new Error("unified media/native caption contract missing");
for(const contract of ['id="create-person"','id="new-person-name"','id="display-rename"','id="rename-preview"'])if(!html.includes(contract))throw new Error(`speaker naming control missing: ${contract}`);
if(!source.includes("currentPerson.name} →")||!source.includes("data.preview.meetings")||!source.includes("speakerUndoName"))throw new Error("speaker impact preview/context-preserving undo missing");
console.log("companion frontend: mobile, bilingual, progress and API boundaries passed");
