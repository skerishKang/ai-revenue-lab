// Living Travel — Staging traveler dashboard logic.
import { onAuth, signOutUser } from "./firebase.js";
import { api, describeError } from "./api.js";
import { badge, clear, el, keyValue, listText, renderStructured, setHidden, setText } from "./dom.js";

const statusEl = document.getElementById("status");
const errorRegion = document.getElementById("error-region");
const tName = document.getElementById("t-name");
const tMeta = document.getElementById("t-meta");
const tStatus = document.getElementById("t-status");
const tPrefs = document.getElementById("t-prefs");
const tEditions = document.getElementById("t-editions");
const editionDetail = document.getElementById("t-edition-detail");
const edTitle = document.getElementById("ed-title");
const edBody = document.getElementById("ed-body");
const edClose = document.getElementById("ed-close");
const fbText = document.getElementById("fb-text");
const fbSubmit = document.getElementById("fb-submit");
const fbResult = document.getElementById("fb-result");
const deactivateBtn = document.getElementById("deactivate-btn");
const deactivateResult = document.getElementById("deactivate-result");
const signoutLink = document.getElementById("signout-link");

let currentEditionId = null;

function showError(message) {
  setText(errorRegion, message);
  setHidden(errorRegion, !message);
}

function renderPreferences(prefs) {
  clear(tPrefs);
  const rows = [
    ["목적지", prefs.destination],
    ["기간(박)", prefs.trip_duration_nights],
    ["여행 맥락", prefs.trip_context],
    ["예산 성향", prefs.budget_tendency],
    ["페이스", prefs.pace_preference],
    ["취향", listText(prefs.interests)],
    ["제외", listText(prefs.exclusions)],
    ["톤", prefs.tone_preference],
    ["분량", prefs.length_preference],
    ["언어", prefs.preferred_language],
  ];
  for (const [label, value] of rows) {
    tPrefs.appendChild(keyValue(label, value));
  }
}

// Render structured_content defensively using only safe DOM APIs.
async function openEdition(editionId) {
  showError("");
  setText(fbResult, "");
  try {
    const edition = await api.get(`/traveler/editions/${encodeURIComponent(editionId)}`);
    currentEditionId = edition.id;
    setText(edTitle, `Edition #${edition.edition_number}`);
    renderStructured(edition.structured_content, edBody);
    setHidden(editionDetail, false);
    editionDetail.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError(describeError(err));
  }
}

function renderEditions(editions) {
  clear(tEditions);
  if (!editions || editions.length === 0) {
    tEditions.appendChild(el("p", { class: "empty-state" }, ["발행된 에디션이 아직 없습니다."]));
    return;
  }
  for (const edition of editions) {
    const item = el("div", { class: "edition-entry" });
    const header = el("div", { class: "edition-entry-header" }, [
      el("span", { class: "edition-entry-number" }, [`#${edition.edition_number}`]),
      badge(edition.publication_state, "badge badge-published"),
    ]);
    const meta = el("div", { class: "edition-entry-meta" }, [
      el("span", {}, [edition.generation_status]),
      el("span", {}, [edition.created_at || ""]),
    ]);
    const actions = el("div", { class: "edition-entry-actions" }, [
      el(
        "button",
        {
          type: "button",
          class: "btn btn-sm btn-accent",
          onClick: () => openEdition(edition.id),
        },
        ["읽기"]
      ),
    ]);
    item.appendChild(header);
    item.appendChild(meta);
    item.appendChild(actions);
    tEditions.appendChild(item);
  }
}

async function loadDashboard() {
  showError("");
  setText(statusEl, "불러오는 중…");
  try {
    const [prefs, editions] = await Promise.all([
      api.get("/traveler/preferences"),
      api.get("/traveler/editions"),
    ]);
    renderPreferences(prefs);
    setText(tName, `${prefs.destination || "여행"} 여행`);
    setText(tMeta, `${prefs.trip_duration_nights || 0}박 · ${prefs.preferred_language || "ko"}`);
    setText(tStatus, "active");
    tStatus.className = "badge badge-active";
    renderEditions(editions.editions);
    setText(statusEl, "");
  } catch (err) {
    setText(statusEl, "");
    showError(describeError(err));
  }
}

onAuth((user) => {
  if (!user) {
    window.location.assign("index.html");
    return;
  }
  api
    .get("/me")
    .then((me) => {
      if (me.role !== "traveler") {
        window.location.assign("index.html");
        return;
      }
      loadDashboard();
    })
    .catch((err) => showError(describeError(err)));
});

edClose.addEventListener("click", () => {
  setHidden(editionDetail, true);
  currentEditionId = null;
});

fbSubmit.addEventListener("click", async () => {
  showError("");
  if (!currentEditionId) {
    setText(fbResult, "에디션을 먼저 열어주세요.");
    return;
  }
  setText(fbResult, "제출 중…");
  try {
    await api.post("/traveler/feedback", {
      edition_id: currentEditionId,
      direction_choices: [],
      selected_section_id: "",
      free_text: fbText.value,
    });
    setText(fbResult, "피드백이 접수되었습니다.");
    fbText.value = "";
  } catch (err) {
    setText(fbResult, "");
    showError(describeError(err));
  }
});

deactivateBtn.addEventListener("click", async () => {
  showError("");
  setText(deactivateResult, "처리 중…");
  try {
    await api.post("/traveler/deactivation-request", {});
    setText(deactivateResult, "탈퇴 요청이 접수되었습니다 (pending).");
  } catch (err) {
    setText(deactivateResult, "");
    showError(describeError(err));
  }
});

signoutLink.addEventListener("click", async (event) => {
  event.preventDefault();
  await signOutUser();
  window.location.assign("index.html");
});
