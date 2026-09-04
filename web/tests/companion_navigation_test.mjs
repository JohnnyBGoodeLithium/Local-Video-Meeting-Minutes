import {clearSessionState, loadTrackedJobs, state, trackJob} from "../static/companion-state.js";

const values=new Map();
globalThis.sessionStorage={getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};

trackJob({id:"job-safe",title:"Synthetic upload",status:"running",phase:"private-path"});
const stored=JSON.parse(values.get("companion:tracked-jobs:v2"));
if(JSON.stringify(stored)!==JSON.stringify([{id:"job-safe",title:"Synthetic upload"}]))throw new Error("unsafe job details persisted");
state.trackedJobs.clear();
loadTrackedJobs();
if(!state.trackedJobs.has("job-safe"))throw new Error("tracked job not restored");
clearSessionState();
if(values.size)throw new Error("revoked session did not clear tracked jobs");

globalThis.location={hash:"#item/item%20safe/transcript"};
globalThis.history={calls:[],pushState(...args){this.calls.push(["push",...args])},replaceState(...args){this.calls.push(["replace",...args])}};
globalThis.dispatchEvent=()=>{};
globalThis.addEventListener=()=>{};
globalThis.CustomEvent=class{constructor(type,init){this.type=type;this.detail=init.detail}};
const {parseRoute,setRoute}=await import("../static/companion-router.js");
const restored=parseRoute();
if(restored.id!=="item safe"||restored.tab!=="transcript")throw new Error("item route did not restore safely");
setRoute({name:"job",id:"job/id"});
if(!history.calls[0][3].endsWith("#job/job%2Fid"))throw new Error("route id was not encoded");
console.log("companion navigation: route restore, encoding and safe tracked jobs passed");
