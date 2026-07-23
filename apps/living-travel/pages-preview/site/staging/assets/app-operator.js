// Living Travel — Staging operator desk logic.
import { onAuth, signOutUser } from "./firebase.js";
import { api, describeError } from "./api.js";
import { badge, clear, el, keyValue, renderStructured, setHidden, setText } from "./dom.js";

const statusEl = document.getElementById("status");
const errorRegion = document.getElementById("error-region");
const opSummary = document.getElementById("op-summary");
const opTravelers = document.getElementById("op-travelers");
const opRefresh = document.getElementById("op-refresh");

const ntName = document.getElementById("nt-name");
const ntDest = document.getElementById("nt-dest");
const ntNights = document.getElementById("nt-nights");
const ntCreate = document.getElementById("nt-create");
const ntResult = document.getElementById("nt-result");

const detail = document.getElementById("op-detail");
const detailName = document.getElementById("detail-name");
const detailInfo = document.getElementById("detail-info");
const detailClose = document.getElementById("detail-close");
const detailResult = document.getElementById("detail-result");
const detailInvite = document.getElementById("detail-invite");
const detailInviteCode = document.getElementById("detail-invite-code");
const detailEditions = document.getElementById("detail-editions");

const editionPanel = document.getElementById("op-edition");
const editionTitle = document.getElementById("edition-title");
const editionBody = document.getElementById("edition-body");
const editionClose = document.getElementById("edition-close");
const editionPublish = document.getElementById("edition-publish");
const editionReject = document.getElementById("edition-reject");
const editionResult = document.getElementById("edition-result");

const signoutLink = document.getElementById("signout-link");

let currentTravelerId = null;
let currentEditionId = null;

function showError(message) {
  setText(errorRegion, message);
  setHidden(errorRegion, !message);
}

function renderTravelers(travelers) {
  clear(opTravelers);
  if (!travelers || travelers.length === 0) {
    opTravelers.appendChild(el("p", { class: "empty-state" }, ["No travelers yet."]));
    return;
  }
  for (const t of travelers) {
    const row = el("div", { class: "operator-traveler-row" });
    row.appendChild(
      el("div", {}, [
        el("strong", { class: "operator-traveler-name" }, [t.display_name]),
        el("span", { class: "operator-traveler-meta" }, [
          `${t.destination || "—"} · ${t.trip_duration_nights || 0} nights`,
        ]),
      ])
    );
    row.appendChild(badge(t.status, t.status === "active" ? "badge badge-active" : "badge badge-rejected"));
    row.appendChild(
      el(
        "button",
        { type: "button", class: "btn btn-sm btn-outline", onClick: () => openTraveler(t.id) },
        ["View"]
      )
    );
    opTravelers.appendChild(row);
  }
}

async function loadTravelers() {
  showError("");
  setText(statusEl, "Loading…");
  try {
    const data = await api.get("/operator/travelers");
    renderTravelers(data.travelers);
    const active = data.travelers.filter((t) => t.status === "active").length;
    setText(opSummary, `${data.travelers.length} travelers · ${active} active`);
    setText(statusEl, "");
  } catch (err) {
    setText(statusEl, "");
    showError(describeError(err));
  }
}

function renderDetailInfo(t) {
  clear(detailInfo);
  const rows = [
    ["ID", t.id],
    ["Display name", t.display_name],
    ["Destination", t.destination],
    ["Nights", t.trip_duration_nights],
    ["Context", t.trip_context],
    ["Budget", t.budget_tendency],
    ["Pace", t.pace_preference],
    ["Tone", t.tone_preference],
    ["Length", t.length_preference],
    ["Language", t.preferred_language],
    ["Status", t.status],
  ];
  for (const [label, value] of rows) {
    detailInfo.appendChild(keyValue(label, value));
  }
}

function renderDetailEditions(editions) {
  clear(detailEditions);
  if (!editions || editions.length === 0) {
    detailEditions.appendChild(el("p", { class: "empty-state" }, ["No editions."]));
    return;
  }
  for (const ed of editions) {
    const row = el("div", { class: "operator-edit-row" });
    row.appendChild(el("span", {}, [`Edition #${ed.edition_number}`]));
    row.appendChild(badge(ed.publication_state, "badge"));
    row.appendChild(
      el(
        "button",
        { type: "button", class: "btn btn-sm btn-outline", onClick: () => openEdition(ed.id) },
        ["Preview"]
      )
    );
    detailEditions.appendChild(row);
  }
}

async function openTraveler(travelerId) {
  showError("");
  setText(detailResult, "");
  setHidden(detailInvite, true);
  try {
    const data = await api.get(`/operator/travelers/${encodeURIComponent(travelerId)}`);
    currentTravelerId = travelerId;
    setText(detailName, data.traveler.display_name);
    renderDetailInfo(data.traveler);
    renderDetailEditions(data.editions);
    setHidden(detail, false);
    detail.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError(describeError(err));
  }
}

async function travelerAction(path, successText) {
  showError("");
  setText(detailResult, "Working…");
  try {
    const result = await api.post(
      `/operator/travelers/${encodeURIComponent(currentTravelerId)}${path}`,
      {}
    );
    setText(detailResult, successText);
    if (result && result.invitation_code) {
      setText(detailInviteCode, result.invitation_code);
      setHidden(detailInvite, false);
    }
    await openTraveler(currentTravelerId);
    await loadTravelers();
  } catch (err) {
    setText(detailResult, "");
    showError(describeError(err));
  }
}

async function openEdition(editionId) {
  showError("");
  setText(editionResult, "");
  try {
    const edition = await api.get(`/operator/editions/${encodeURIComponent(editionId)}`);
    currentEditionId = edition.id;
    setText(editionTitle, `Edition #${edition.edition_number} · ${edition.publication_state}`);
    renderStructured(edition.structured_content, editionBody);
    setHidden(editionPanel, false);
    editionPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError(describeError(err));
  }
}

async function publicationAction(path) {
  showError("");
  setText(editionResult, "Working…");
  try {
    const result = await api.post(
      `/operator/editions/${encodeURIComponent(currentEditionId)}${path}`,
      {}
    );
    setText(editionResult, `publication_state: ${result.publication_state}`);
    if (currentTravelerId) {
      await openTraveler(currentTravelerId);
    }
  } catch (err) {
    setText(editionResult, "");
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
      if (me.role !== "operator") {
        window.location.assign("index.html");
        return;
      }
      loadTravelers();
    })
    .catch((err) => showError(describeError(err)));
});

opRefresh.addEventListener("click", loadTravelers);

ntCreate.addEventListener("click", async () => {
  showError("");
  setText(ntResult, "Creating…");
  try {
    const created = await api.post("/operator/travelers", {
      display_name: ntName.value.trim(),
      destination: ntDest.value.trim(),
      trip_duration_nights: Number(ntNights.value) || 2,
    });
    setText(ntResult, `Created traveler ${created.id}.`);
    ntName.value = "";
    ntDest.value = "";
    await loadTravelers();
  } catch (err) {
    setText(ntResult, "");
    showError(describeError(err));
  }
});

detailClose.addEventListener("click", () => {
  setHidden(detail, true);
  currentTravelerId = null;
});

document.getElementById("act-invite").addEventListener("click", () =>
  travelerAction("/invite", "Invitation code issued.")
);
document.getElementById("act-rotate").addEventListener("click", () =>
  travelerAction("/rotate-invite", "Invitation code rotated.")
);
document.getElementById("act-activate").addEventListener("click", () =>
  travelerAction("/activate", "Traveler activated.")
);
document.getElementById("act-deactivate").addEventListener("click", () =>
  travelerAction("/deactivate", "Traveler deactivated.")
);
document.getElementById("act-gen1").addEventListener("click", () =>
  travelerAction("/generate-first", "First edition generated (pending review).")
);
document.getElementById("act-gen2").addEventListener("click", () =>
  travelerAction("/generate-second", "Second edition generated (pending review).")
);

editionClose.addEventListener("click", () => {
  setHidden(editionPanel, true);
  currentEditionId = null;
});
editionPublish.addEventListener("click", () => publicationAction("/publish"));
editionReject.addEventListener("click", () => publicationAction("/reject"));

signoutLink.addEventListener("click", async (event) => {
  event.preventDefault();
  await signOutUser();
  window.location.assign("index.html");
});
