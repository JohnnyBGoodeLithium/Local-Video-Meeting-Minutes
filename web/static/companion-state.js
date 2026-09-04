export const JOB_STORE_KEY = "companion:tracked-jobs:v2";

export const state = {
  currentRoute: {name: "home"},
  selectedItem: null,
  selectedTab: "overview",
  selectedPerson: null,
  playerState: {itemId: null, currentTime: 0},
  trackedJobs: new Map(),
};

export function loadTrackedJobs(storage = sessionStorage) {
  let rows = [];
  try { rows = JSON.parse(storage.getItem(JOB_STORE_KEY) || "[]"); } catch (_) {}
  state.trackedJobs = new Map((Array.isArray(rows) ? rows : [])
    .filter(row => row && typeof row.id === "string")
    .map(row => [row.id, {id: row.id, title: String(row.title || "Processing")}]))
  return state.trackedJobs;
}

export function saveTrackedJobs(storage = sessionStorage) {
  storage.setItem(JOB_STORE_KEY, JSON.stringify(
    [...state.trackedJobs.values()].map(({id, title}) => ({id, title}))));
}

export function trackJob(job) {
  state.trackedJobs.set(job.id, {id: job.id, title: job.title || "Processing", ...job});
  saveTrackedJobs();
}

export function forgetJob(id) {
  state.trackedJobs.delete(id);
  saveTrackedJobs();
}

export function clearSessionState() {
  state.trackedJobs.clear();
  sessionStorage.removeItem(JOB_STORE_KEY);
  sessionStorage.removeItem("companion:job-pointer:v1");
}
