import {state} from "./companion-state.js";

const tabs = new Set(["overview", "chapters", "people", "transcript"]);

export function parseRoute(hash = location.hash) {
  const raw = hash.replace(/^#/, "");
  if (!raw || raw.startsWith("pair=")) return {name: "home"};
  const parts = raw.split("/").map(value => decodeURIComponent(value));
  if (parts[0] === "library" && parts.length === 1) return {name: "library"};
  if (parts[0] === "job" && parts[1]) return {name: "job", id: parts[1]};
  if (parts[0] === "item" && parts[1]) {
    return {name: "item", id: parts[1], tab: tabs.has(parts[2]) ? parts[2] : "overview"};
  }
  return {name: "home"};
}

export function routeHash(route) {
  if (route.name === "home") return "";
  if (route.name === "library") return "#library";
  if (route.name === "job") return `#job/${encodeURIComponent(route.id)}`;
  if (route.name === "item") {
    return `#item/${encodeURIComponent(route.id)}/${route.tab || "overview"}`;
  }
  return "";
}

export function setRoute(route, {replace = false} = {}) {
  state.currentRoute = route;
  const url = `/companion${routeHash(route)}`;
  history[replace ? "replaceState" : "pushState"]({companionRoute: route}, "", url);
  dispatchEvent(new CustomEvent("companionroute", {detail: route}));
}

export function startRouter() {
  const restore = () => {
    state.currentRoute = parseRoute();
    dispatchEvent(new CustomEvent("companionroute", {detail: state.currentRoute}));
  };
  addEventListener("popstate", restore);
  restore();
}
