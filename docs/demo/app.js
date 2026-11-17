/**
 * AEGIS Static Demo & Replay Viewer
 * Operates purely client-side without a backend.
 * Replays real adversarial_duel_log.json and results.csv files.
 * If data is absent, displays "no data yet" rather than mock figures.
 */

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const btnLoadDefaultDuel = document.getElementById("btnLoadDefaultDuel");
  const duelFileInput = document.getElementById("duelFileInput");
  const duelEmptyState = document.getElementById("duelEmptyState");
  const duelContent = document.getElementById("duelContent");

  const btnLoadDefaultBench = document.getElementById("btnLoadDefaultBench");
  const benchFileInput = document.getElementById("benchFileInput");
  const benchEmptyState = document.getElementById("benchEmptyState");
  const benchContent = document.getElementById("benchContent");

  // Attempt to load default files on startup
  tryFetchDuelTranscript(["adversarial_duel_log.json", "../../adversarial_duel_log.json"]);
  tryFetchBenchmarkCSV(["results.csv", "../../bench/results/results.csv"]);

  // Event Listeners
  btnLoadDefaultDuel.addEventListener("click", () => {
    tryFetchDuelTranscript(["adversarial_duel_log.json", "../../adversarial_duel_log.json"]);
  });

  duelFileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const data = JSON.parse(event.target.result);
        renderDuelTranscript(data);
      } catch (err) {
        alert("Failed to parse JSON: " + err.message);
      }
    };
    reader.readAsText(file);
  });

  btnLoadDefaultBench.addEventListener("click", () => {
    tryFetchBenchmarkCSV(["results.csv", "../../bench/results/results.csv"]);
  });

  benchFileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      renderBenchmarkCSV(event.target.result);
    };
    reader.readAsText(file);
  });

  // Fetch helpers
  function tryFetchDuelTranscript(paths) {
    if (paths.length === 0) {
      showDuelEmpty();
      return;
    }
    const currentPath = paths[0];
    fetch(currentPath)
      .then(res => {
        if (!res.ok) throw new Error("Not found");
        return res.json();
      })
      .then(data => {
        if (data && Array.isArray(data) && data.length > 0) {
          renderDuelTranscript(data);
        } else {
          showDuelEmpty();
        }
      })
      .catch(() => {
        tryFetchDuelTranscript(paths.slice(1));
      });
  }

  function tryFetchBenchmarkCSV(paths) {
    if (paths.length === 0) {
      showBenchEmpty();
      return;
    }
    const currentPath = paths[0];
    fetch(currentPath)
      .then(res => {
        if (!res.ok) throw new Error("Not found");
        return res.text();
      })
      .then(csvText => {
        if (csvText && csvText.trim().length > 0) {
          renderBenchmarkCSV(csvText);
        } else {
          showBenchEmpty();
        }
      })
      .catch(() => {
        tryFetchBenchmarkCSV(paths.slice(1));
      });
  }

  function showDuelEmpty() {
    duelEmptyState.style.display = "block";
    duelContent.style.display = "none";
  }

  function showBenchEmpty() {
    benchEmptyState.style.display = "block";
    benchContent.style.display = "none";
  }

  function renderDuelTranscript(rounds) {
    duelEmptyState.style.display = "none";
    duelContent.style.display = "block";
    duelContent.innerHTML = "";

    rounds.forEach(r => {
      const roundDiv = document.createElement("div");
      roundDiv.className = "round-card";
      
      const statusClass = r.status === "HARDENED" ? "round-status-hardened" : "round-status-partial";
      
      let breachesHtml = "";
      (r.breaches || []).forEach((b, idx) => {
        const isVerified = (b.status === "VERIFIED_PATCHED");
        const tagClass = isVerified ? "tag-verified" : "tag-unresolved";
        const tagText = isVerified ? "VERIFIED PATCHED" : "UNRESOLVED";
        
        breachesHtml += `
          <div class="breach-item">
            <div class="breach-header">
              <strong>#${idx + 1} [Tier ${b.tier || '?'}] ${escapeHtml(b.type || 'Vulnerability')}</strong>
              <span class="status-tag ${tagClass}">${tagText}</span>
            </div>
            <div style="font-size: 13px; color: #cbd5e1; margin-bottom: 6px;">
              <code>${escapeHtml(b.method || 'GET')} ${escapeHtml(b.route || '/')}</code> &bull; Payload: <code>${escapeHtml(String(b.payload || 'None'))}</code>
            </div>
            <div style="font-size: 12px; color: #94a3b8;">
              ${escapeHtml(b.details || '')}
            </div>
          </div>
        `;
      });

      roundDiv.innerHTML = `
        <div class="round-header">
          <div>
            <strong>Round ${r.round}</strong>
            <span style="margin-left: 10px; font-size: 13px; color: #94a3b8;">
              Verified: ${r.verified_fixes || 0} | Unresolved: ${r.unresolved || 0}
            </span>
          </div>
          <span class="${statusClass}">${escapeHtml(r.status || 'UNKNOWN')}</span>
        </div>
        <div class="breach-list">
          ${breachesHtml || '<p style="color: #94a3b8; font-size: 13px;">No breaches in this round.</p>'}
        </div>
      `;
      duelContent.appendChild(roundDiv);
    });
  }

  function renderBenchmarkCSV(csvText) {
    const lines = csvText.trim().split("\n");
    if (lines.length < 2) {
      showBenchEmpty();
      return;
    }

    benchEmptyState.style.display = "none";
    benchContent.style.display = "block";
    benchContent.innerHTML = "";

    const headers = parseCSVLine(lines[0]);
    let tableHtml = `<div class="table-responsive"><table><thead><tr>`;
    headers.forEach(h => {
      tableHtml += `<th>${escapeHtml(h)}</th>`;
    });
    tableHtml += `</tr></thead><tbody>`;

    for (let i = 1; i < lines.length; i++) {
      const row = parseCSVLine(lines[i]);
      if (row.length === headers.length) {
        tableHtml += `<tr>`;
        row.forEach(val => {
          tableHtml += `<td>${escapeHtml(val)}</td>`;
        });
        tableHtml += `</tr>`;
      }
    }
    tableHtml += `</tbody></table></div>`;
    benchContent.innerHTML = tableHtml;
  }

  function parseCSVLine(line) {
    const result = [];
    let insideQuotes = false;
    let entry = "";
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') {
        insideQuotes = !insideQuotes;
      } else if (c === ',' && !insideQuotes) {
        result.push(entry.trim());
        entry = "";
      } else {
        entry += c;
      }
    }
    result.push(entry.trim());
    return result;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});
