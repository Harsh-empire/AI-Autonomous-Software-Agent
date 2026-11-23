// =============================================================================
// AEGIS Dual-AI Web IDE - Complete Interactive Client Engine
// Combines Lovable-Style Experience with Autonomous Builder vs Hacker Arena
// =============================================================================

document.addEventListener("DOMContentLoaded", () => {
    let ws = null;
    let currentProject = "simple_task_management_app";
    let activeFile = "app.py";
    let breachCount = 0;
    let pendingPrompt = null;

    // --- DOM View Screens ---
    const viewLanding = document.getElementById("view-landing");
    const viewDashboard = document.getElementById("view-dashboard");
    const viewStudio = document.getElementById("view-studio");
    const modalLogin = document.getElementById("modal-login");

    // --- Landing Elements ---
    const landingPromptInput = document.getElementById("landing-prompt-input");
    const landingPromptSubmit = document.getElementById("landing-prompt-submit");

    // --- Dashboard Elements ---
    const dashPromptInput = document.getElementById("dashboard-prompt-input");
    const btnDashCreate = document.getElementById("btn-dash-create");
    const dashModelSelect = document.getElementById("dash-model-select");

    // --- Studio Elements ---
    const btnBackDashboard = document.getElementById("btn-back-dashboard");
    const projectSelect = document.getElementById("project-select");
    const modelSelect = document.getElementById("model-select");
    const fileTree = document.getElementById("file-tree");
    const promptInput = document.getElementById("prompt-input");
    const btnBuild = document.getElementById("btn-build");
    const btnCancelBuild = document.getElementById("btn-cancel-build");
    const buildProgressPanel = document.getElementById("build-progress-panel");
    const buildCurrentStage = document.getElementById("build-current-stage");
    const buildElapsedTimer = document.getElementById("build-elapsed-timer");
    const buildStageMessage = document.getElementById("build-stage-message");
    const missingDepsBanner = document.getElementById("missing-deps-banner");
    const missingDepsText = document.getElementById("missing-deps-text");
    const btnInstallDeps = document.getElementById("btn-install-deps");
    const buildErrorBanner = document.getElementById("build-error-banner");
    const buildErrorText = document.getElementById("build-error-text");
    const buildErrorLogTail = document.getElementById("build-error-log-tail");
    const ollamaStatusBanner = document.getElementById("ollama-status-banner");
    const btnTriggerDuel = document.getElementById("btn-trigger-duel");
    const btnRefreshFiles = document.getElementById("btn-refresh-files");
    const duelStream = document.getElementById("duel-stream");
    const codeDisplay = document.getElementById("code-display");
    const activeFileLabel = document.getElementById("active-file-label");
    const editorCurrentPath = document.getElementById("editor-current-path");
    const appPreviewFrame = document.getElementById("app-preview-frame");
    const btnReloadPreview = document.getElementById("btn-reload-preview");
    const shieldScore = document.getElementById("shield-score");
    const shieldBar = document.getElementById("shield-bar");
    const breachCounter = document.getElementById("breach-counter");
    const chatInput = document.getElementById("chat-input");
    const btnChatSend = document.getElementById("btn-chat-send");

    // =========================================================================
    // 1. VIEW ROUTING & AUTH MANAGEMENT
    // =========================================================================

    function getCurrentUser() {
        try {
            return JSON.parse(localStorage.getItem("aegis_user"));
        } catch {
            return null;
        }
    }

    function switchView(viewName) {
        viewLanding.classList.remove("active");
        viewDashboard.classList.remove("active");
        viewStudio.classList.remove("active");

        if (viewName === "landing") {
            viewLanding.classList.add("active");
        } else if (viewName === "dashboard") {
            viewDashboard.classList.add("active");
        } else if (viewName === "studio") {
            viewStudio.classList.add("active");
        }
        window.scrollTo(0, 0);
    }

    function openLoginModal() {
        modalLogin.classList.add("active");
    }

    function closeLoginModal() {
        modalLogin.classList.remove("active");
    }

    function loginUser(userName, userEmail) {
        const user = { name: userName || "Harsh", email: userEmail || "harsh@aegis.ai" };
        localStorage.setItem("aegis_user", JSON.stringify(user));
        closeLoginModal();

        // If there was a pending prompt typed before login, execute it in Studio
        if (pendingPrompt) {
            const promptToRun = pendingPrompt;
            pendingPrompt = null;
            switchView("studio");
            executeBuildPipeline(promptToRun);
        } else {
            switchView("dashboard");
        }
    }

    function logoutUser() {
        localStorage.removeItem("aegis_user");
        switchView("landing");
    }

    function setupAuthAndViews() {
        const user = getCurrentUser();
        if (user) {
            switchView("dashboard");
        } else {
            switchView("landing");
        }

        // Open login buttons
        document.querySelectorAll(".btn-open-login").forEach(btn => {
            btn.addEventListener("click", openLoginModal);
        });

        // Close login button
        const btnCloseLogin = document.getElementById("btn-close-login");
        if (btnCloseLogin) btnCloseLogin.addEventListener("click", closeLoginModal);

        // Click outside modal to close
        modalLogin.addEventListener("click", (e) => {
            if (e.target === modalLogin) closeLoginModal();
        });

        // Login options
        const btnLoginDemo = document.getElementById("btn-login-demo");
        if (btnLoginDemo) {
            btnLoginDemo.addEventListener("click", () => loginUser("Local Developer (Demo)", "dev@local"));
        }

        // Logout
        document.querySelectorAll(".btn-logout-icon").forEach(btn => {
            btn.addEventListener("click", logoutUser);
        });

        // Studio "Back to Dashboard" button
        if (btnBackDashboard) {
            btnBackDashboard.addEventListener("click", () => switchView("dashboard"));
        }

        // Sidebar navigation items
        document.querySelectorAll('.dash-sidebar [data-view="dashboard"]').forEach(btn => {
            btn.addEventListener("click", () => switchView("dashboard"));
        });
        document.querySelectorAll('.dash-sidebar [data-action="open-studio"]').forEach(btn => {
            btn.addEventListener("click", () => switchView("studio"));
        });
    }

    // =========================================================================
    // 2. DYNAMIC MODEL SELECTOR & SYNC
    // =========================================================================

    async function loadModels() {
        try {
            const res = await fetch("/api/models");
            if (!res.ok) return;
            const data = await res.json();
            
            const syncSelects = document.querySelectorAll(".model-picker-sync");
            syncSelects.forEach(select => {
                const currentVal = select.value;
                select.innerHTML = "";

                // Group 1: Local Ollama
                const optGroupLocal = document.createElement("optgroup");
                optGroupLocal.label = "Local Ollama Engines";
                const ollamaList = (data.ollama && data.ollama.length > 0) ? data.ollama : ["qwen2.5-coder:7b"];
                ollamaList.forEach(m => {
                    const opt = document.createElement("option");
                    opt.value = m;
                    opt.textContent = `⚡ ${m} (Local)`;
                    if (m === "qwen2.5-coder:7b" || m === currentVal) opt.selected = true;
                    optGroupLocal.appendChild(opt);
                });
                select.appendChild(optGroupLocal);
            });
        } catch (e) {
            console.warn("Could not fetch models dynamically:", e);
        }
    }

    function setupModelSync() {
        document.querySelectorAll(".model-picker-sync").forEach(sel => {
            sel.addEventListener("change", (e) => {
                const val = e.target.value;
                document.querySelectorAll(".model-picker-sync").forEach(other => {
                    other.value = val;
                });
                checkOllamaHealth();
            });
        });
    }

    function getSelectedModel() {
        if (modelSelect && modelSelect.value) return modelSelect.value;
        if (dashModelSelect && dashModelSelect.value) return dashModelSelect.value;
        return "qwen2.5-coder:7b";
    }

    // =========================================================================
    // 3. PROJECT & FILE SYSTEM MANAGEMENT
    // =========================================================================

    async function loadProjects() {
        try {
            const res = await fetch("/api/projects");
            if (!res.ok) return;
            const data = await res.json();
            if (projectSelect) {
                projectSelect.innerHTML = "";
                data.projects.forEach(p => {
                    const opt = document.createElement("option");
                    opt.value = p;
                    opt.textContent = p;
                    if (p === currentProject) opt.selected = true;
                    projectSelect.appendChild(opt);
                });
            }
        } catch (e) {
            console.error("Error loading projects:", e);
        }
    }

    async function loadFiles(proj) {
        try {
            const res = await fetch(`/api/project-files?project=${encodeURIComponent(proj)}`);
            if (!res.ok) return;
            const data = await res.json();
            if (!fileTree) return;
            fileTree.innerHTML = "";
            data.files.forEach(f => {
                const li = document.createElement("li");
                li.className = `file-tree-item ${f === activeFile ? 'active' : ''}`;
                const ext = f.split('.').pop();
                let icon = "📄";
                if (ext === "py") icon = "🐍";
                else if (ext === "html") icon = "🌐";
                else if (ext === "css") icon = "🎨";
                else if (ext === "json") icon = "⚙️";

                li.innerHTML = `<span>${icon}</span> <span>${f}</span>`;
                li.addEventListener("click", () => {
                    document.querySelectorAll(".file-tree-item").forEach(el => el.classList.remove("active"));
                    li.classList.add("active");
                    activeFile = f;
                    loadFileContent(proj, f);
                });
                fileTree.appendChild(li);
            });
        } catch (e) {
            console.error("Error loading files:", e);
        }
    }

    async function loadFileContent(proj, file) {
        try {
            if (activeFileLabel) activeFileLabel.textContent = `Code Editor (${file})`;
            if (editorCurrentPath) editorCurrentPath.textContent = `${proj}/${file}`;
            const res = await fetch(`/api/file-content?project=${encodeURIComponent(proj)}&file=${encodeURIComponent(file)}`);
            if (!res.ok) {
                if (codeDisplay) codeDisplay.textContent = "# File not found or empty";
                return;
            }
            const text = await res.text();
            if (codeDisplay) codeDisplay.textContent = text;
        } catch (e) {
            console.error("Error reading file:", e);
        }
    }

    function reloadPreview() {
        if (!appPreviewFrame) return;
        const currentSrc = appPreviewFrame.src.split('?')[0];
        appPreviewFrame.src = `${currentSrc}?t=${Date.now()}`;
    }

    // =========================================================================
    // 4. WEBSOCKET REAL-TIME DUAL-AI ARENA STREAMING
    // =========================================================================

    function connectWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log("⚔️ Connected to Dual-AI Arena WebSocket");
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleWebSocketMessage(msg);
            } catch (e) {
                console.error("Malformed WebSocket message:", event.data);
            }
        };

        ws.onclose = () => {
            setTimeout(connectWebSocket, 3000);
        };
    }

    function resetBuildUI() {
        if (btnBuild) btnBuild.disabled = false;
        if (btnTriggerDuel) btnTriggerDuel.disabled = false;
        if (btnCancelBuild) btnCancelBuild.style.display = "none";
        if (buildProgressPanel) buildProgressPanel.style.display = "none";
    }

    function handleWebSocketMessage(msg) {
        if (msg.type === "speech") {
            appendSpeechBubble(msg.speaker, msg.text, msg.avatar);
        } else if (msg.type === "build_progress") {
            if (buildProgressPanel) buildProgressPanel.style.display = "block";
            if (buildCurrentStage) buildCurrentStage.textContent = `Stage: ${msg.stage}`;
            if (buildElapsedTimer) buildElapsedTimer.textContent = `${msg.elapsed}s`;
            if (buildStageMessage) buildStageMessage.textContent = msg.text || "";

            const rawStage = (msg.stage || "").toLowerCase();
            const stageKey = rawStage.split(" ")[0]; // e.g. "generate 1/3" -> "generate"
            ["analyze", "plan", "generate", "check", "start", "smoke", "repair"].forEach(s => {
                const el = document.getElementById(`stage-li-${s}`);
                if (!el) return;
                if (s === stageKey) {
                    el.style.color = "#38bdf8";
                    el.style.fontWeight = "600";
                    el.textContent = el.textContent.replace(/^[🟢⏳⚪]/, "⏳");
                } else if (rawStage.includes(s)) {
                    el.style.color = "#38bdf8";
                }
            });
        } else if (msg.type === "heartbeat") {
            if (buildElapsedTimer) buildElapsedTimer.textContent = `${msg.elapsed}s`;
            if (buildStageMessage) buildStageMessage.textContent = msg.text;
        } else if (msg.type === "build_folder_created") {
            currentProject = msg.project;
            loadProjects();
            loadFiles(currentProject);
            appendSystemNotice(`📁 Project folder created: '${currentProject}'`);
        } else if (msg.type === "missing_dependencies") {
            resetBuildUI();
            if (missingDepsBanner) {
                missingDepsBanner.style.display = "block";
                if (missingDepsText) missingDepsText.textContent = msg.text;
                if (btnInstallDeps) {
                    btnInstallDeps.disabled = false;
                    btnInstallDeps.textContent = "Install into project .venv";
                    btnInstallDeps.onclick = () => {
                        btnInstallDeps.disabled = true;
                        btnInstallDeps.textContent = "Installing dependencies...";
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({ action: "install_dependencies", packages: msg.packages }));
                        }
                    };
                }
            }
            appendSystemNotice(`⚠️ Missing dependencies detected: ${msg.packages ? msg.packages.join(', ') : ''}`);
        } else if (msg.type === "dependencies_installed") {
            if (missingDepsBanner) missingDepsBanner.style.display = "none";
            appendSystemNotice(`✅ ${msg.text}`);
        } else if (msg.type === "build_cancelled") {
            resetBuildUI();
            if (appPreviewFrame && appPreviewFrame.hasAttribute("srcdoc")) {
                appPreviewFrame.removeAttribute("srcdoc");
            }
            reloadPreview();
            appendSystemNotice(`🛑 ${msg.text}`);
        } else if (msg.type === "breach") {
            breachCount++;
            if (breachCounter) breachCounter.textContent = `${breachCount} Breach${breachCount > 1 ? 'es' : ''}`;
            appendBreachCard(msg.breach);
            updateShield(Math.max(40, 100 - breachCount * 15));
        } else if (msg.type === "patch") {
            appendSystemNotice(`🛠️ Builder deployed defensive patch to '${msg.file}'`);
            if (msg.diff) {
                renderDiff(msg.diff);
            }
            loadFiles(currentProject);
            if (activeFile === msg.file || msg.file === "app.py") {
                loadFileContent(currentProject, activeFile);
            }
        } else if (msg.type === "server_restart") {
            resetBuildUI();
            if (appPreviewFrame && appPreviewFrame.hasAttribute("srcdoc")) {
                appPreviewFrame.removeAttribute("srcdoc");
            }
            reloadPreview();
        } else if (msg.type === "project_switched") {
            resetBuildUI();
            currentProject = msg.project;
            loadProjects();
            loadFiles(currentProject);
            loadFileContent(currentProject, "app.py");
            if (appPreviewFrame && appPreviewFrame.hasAttribute("srcdoc")) {
                appPreviewFrame.removeAttribute("srcdoc");
            }
            reloadPreview();
            appendSystemNotice(`📁 Switched active workspace to: '${currentProject}'`);
        } else if (msg.type === "duel_all_verified") {
            // Server sends this only when every detected breach was verified fixed.
            updateShield(msg.score);
            appendSystemNotice(msg.text || `✅ All probes passed: every detected breach was verified fixed.`);
        } else if (msg.type === "duel_completed") {
            updateShield(msg.score);
            appendSystemNotice(msg.text || `⚠️ Duel finished. See the security audit for details.`);
        } else if (msg.type === "error") {
            resetBuildUI();
            appendSystemNotice(`❌ Error: ${msg.text}`);
            if (buildErrorBanner) {
                buildErrorBanner.style.display = "block";
                if (buildErrorText) buildErrorText.textContent = msg.text;
                if (buildErrorLogTail) {
                    if (msg.log_tail) {
                        buildErrorLogTail.style.display = "block";
                        buildErrorLogTail.textContent = msg.log_tail;
                    } else {
                        buildErrorLogTail.style.display = "none";
                    }
                }
            }
        } else if (msg.type === "info") {
            appendSystemNotice(msg.text);
        }
    }

    function appendSpeechBubble(speaker, text, avatar) {
        if (!duelStream) return;
        const bubble = document.createElement("div");
        const isUser = speaker.toUpperCase() === "USER";
        const isBuilder = speaker.toLowerCase().includes("builder");
        const bubbleClass = isUser ? "user-bubble" : (isBuilder ? "builder-bubble" : "hacker-bubble");
        bubble.className = `duel-bubble ${bubbleClass}`;
        
        const defaultAvatar = isUser ? "👤" : (isBuilder ? "🛠️" : "😈");
        bubble.innerHTML = `
            <div class="bubble-sender">
                <span>${avatar || defaultAvatar}</span>
                <span>${speaker}</span>
            </div>
            <div class="bubble-content">${escapeHTML(text)}</div>
        `;
        duelStream.appendChild(bubble);
        duelStream.scrollTop = duelStream.scrollHeight;
    }

    function appendBreachCard(b) {
        if (!duelStream) return;
        const card = document.createElement("div");
        card.className = "breach-alert-card";
        card.innerHTML = `
            <div class="breach-header">
                <span>🚨 VULNERABILITY BREACH:</span>
                <span>${escapeHTML(b.type || 'Crash')}</span>
            </div>
            <div class="breach-detail">
                Endpoint: [${b.method || 'POST'}] ${b.route || '/'} | Payload: ${escapeHTML(JSON.stringify(b.payload || ''))}
            </div>
            <div class="breach-detail">
                Impact: ${escapeHTML(b.details || '')}
            </div>
        `;
        duelStream.appendChild(card);
        duelStream.scrollTop = duelStream.scrollHeight;
    }

    function appendSystemNotice(text) {
        if (!duelStream) return;
        const notice = document.createElement("div");
        notice.className = "system-announcement";
        notice.innerHTML = `<span class="announcement-icon">⚔️</span> <span>${escapeHTML(text)}</span>`;
        duelStream.appendChild(notice);
        duelStream.scrollTop = duelStream.scrollHeight;
    }

    function updateShield(score) {
        if (!shieldScore || !shieldBar) return;
        // No measured score (duel not run yet, or no breaches found): show a neutral placeholder.
        if (score === null || score === undefined || Number.isNaN(Number(score))) {
            shieldScore.textContent = "--";
            shieldBar.style.width = "0%";
            return;
        }
        shieldScore.textContent = `${score}%`;
        shieldBar.style.width = `${score}%`;
        if (score === 100) {
            shieldBar.style.background = "linear-gradient(90deg, #00ff9d, #00d2ff)";
        } else {
            shieldBar.style.background = "linear-gradient(90deg, #ff0055, #ffcc00)";
        }
    }

    // =========================================================================
    // 5. PROMPT EXECUTION & BUILD PIPELINE
    // =========================================================================

    async function checkOllamaHealth() {
        if (!ollamaStatusBanner) return;
        try {
            const model = getSelectedModel();
            const res = await fetch(`/api/ollama/status?model=${encodeURIComponent(model)}`);
            if (!res.ok) return;
            const data = await res.json();
            if (!data.online) {
                ollamaStatusBanner.style.display = "block";
                ollamaStatusBanner.style.background = "#450a0a";
                ollamaStatusBanner.style.color = "#fca5a5";
                ollamaStatusBanner.textContent = `⚠️ Ollama is unreachable. Start local daemon with: ollama serve`;
            } else if (!data.model_pulled) {
                ollamaStatusBanner.style.display = "block";
                ollamaStatusBanner.style.background = "#431407";
                ollamaStatusBanner.style.color = "#fdba74";
                ollamaStatusBanner.textContent = `⚠️ Model '${model}' not pulled. Run: ollama pull ${model}`;
            } else if (!data.model_loaded) {
                ollamaStatusBanner.style.display = "block";
                ollamaStatusBanner.style.background = "#1e293b";
                ollamaStatusBanner.style.color = "#93c5fd";
                ollamaStatusBanner.textContent = `ℹ️ Model '${model}' ready. (First request loads into RAM/VRAM and can take minutes on CPU).`;
            } else {
                ollamaStatusBanner.style.display = "none";
            }
        } catch {
            // Ignore network errors in health poll
        }
    }

    function executeBuildPipeline(prompt) {
        if (!prompt) return;
        
        // Ensure we are in Studio view
        switchView("studio");

        // Switch to Arena tab
        const arenaTabBtn = document.querySelector('[data-tab="arena-view"]');
        if (arenaTabBtn) arenaTabBtn.click();

        // 1. Update UI controls for build state
        if (btnBuild) btnBuild.disabled = true;
        if (btnTriggerDuel) btnTriggerDuel.disabled = true;
        if (btnCancelBuild) btnCancelBuild.style.display = "inline-block";
        if (buildProgressPanel) buildProgressPanel.style.display = "block";
        if (buildErrorBanner) buildErrorBanner.style.display = "none";
        if (missingDepsBanner) missingDepsBanner.style.display = "none";

        // Reset stages list icons
        ["analyze", "plan", "generate", "check", "start", "smoke", "repair"].forEach(s => {
            const el = document.getElementById(`stage-li-${s}`);
            if (el) {
                el.style.color = "#64748b";
                el.style.fontWeight = "normal";
                el.textContent = el.textContent.replace(/^[🟢⏳⚪]/, "⚪");
            }
        });

        // Replace stale preview with Building placeholder
        if (appPreviewFrame) {
            appPreviewFrame.srcdoc = `<!DOCTYPE html><html><body style="background:#090d16;color:#94a3b8;font-family:sans-serif;height:100vh;margin:0;display:flex;flex-direction:column;align-items:center;justify-content:center;"><h2>🔨 Building Application...</h2><p style="color:#64748b;margin-top:8px;">Synthesizing, verifying, and starting server</p></body></html>`;
        }

        appendSpeechBubble("USER", prompt, "👤");
        appendSystemNotice(`🚀 Launching autonomous dual-AI build pipeline for: "${prompt}"...`);

        if (promptInput) promptInput.value = prompt;

        if (!ws || ws.readyState !== WebSocket.OPEN) {
            setTimeout(() => executeBuildPipeline(prompt), 500);
            return;
        }

        ws.send(JSON.stringify({
            action: "start_build",
            prompt: prompt,
            model: getSelectedModel()
        }));
    }

    function setupPromptListeners() {
        // Landing Prompt Input & Submit
        if (landingPromptSubmit && landingPromptInput) {
            const handleLandingSubmit = () => {
                const val = landingPromptInput.value.trim();
                if (!val) return;
                const user = getCurrentUser();
                if (!user) {
                    pendingPrompt = val;
                    openLoginModal();
                } else {
                    executeBuildPipeline(val);
                }
            };
            landingPromptSubmit.addEventListener("click", handleLandingSubmit);
            landingPromptInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    handleLandingSubmit();
                }
            });
        }

        // Landing Suggestion Chips
        document.querySelectorAll("#view-landing .chip-item").forEach(chip => {
            chip.addEventListener("click", () => {
                const prompt = chip.getAttribute("data-prompt");
                const user = getCurrentUser();
                if (!user) {
                    pendingPrompt = prompt;
                    openLoginModal();
                } else {
                    executeBuildPipeline(prompt);
                }
            });
        });

        // Dashboard Prompt Textarea & Create Button
        if (btnDashCreate && dashPromptInput) {
            const handleDashSubmit = () => {
                const val = dashPromptInput.value.trim();
                if (!val) {
                    alert("Please describe what you want to create!");
                    return;
                }
                executeBuildPipeline(val);
            };
            btnDashCreate.addEventListener("click", handleDashSubmit);
            dashPromptInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleDashSubmit();
                }
            });
        }

        // Dashboard Quick Chips
        document.querySelectorAll(".quick-chip").forEach(chip => {
            chip.addEventListener("click", () => {
                const prompt = chip.getAttribute("data-prompt");
                if (prompt) executeBuildPipeline(prompt);
            });
        });

        // Dashboard Project Cards
        document.querySelectorAll(".project-card").forEach(card => {
            card.addEventListener("click", () => {
                const prompt = card.getAttribute("data-prompt");
                const proj = card.getAttribute("data-project");
                if (prompt) {
                    executeBuildPipeline(prompt);
                } else if (proj) {
                    currentProject = proj;
                    switchView("studio");
                    loadFiles(proj);
                    loadFileContent(proj, "app.py");
                    reloadPreview();
                }
            });
        });

        // Dashboard Recents list items
        document.querySelectorAll(".recent-item").forEach(item => {
            item.addEventListener("click", () => {
                const proj = item.getAttribute("data-project");
                if (proj) {
                    currentProject = proj;
                    switchView("studio");
                    loadFiles(proj);
                    loadFileContent(proj, "app.py");
                    reloadPreview();
                }
            });
        });

        // Studio Prompt Button
        if (btnBuild && promptInput) {
            btnBuild.addEventListener("click", () => {
                const prompt = promptInput.value.trim();
                if (!prompt) {
                    alert("Please describe the application you want to build!");
                    return;
                }
                executeBuildPipeline(prompt);
            });
        }

        // Cancel Build Button
        if (btnCancelBuild) {
            btnCancelBuild.addEventListener("click", () => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ action: "cancel_build" }));
                }
            });
        }

        // Studio Interactive Chat Input
        if (btnChatSend && chatInput) {
            const handleChatSend = () => {
                const text = chatInput.value.trim();
                if (!text) return;
                chatInput.value = "";
                executeBuildPipeline(text);
            };
            btnChatSend.addEventListener("click", handleChatSend);
            chatInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    handleChatSend();
                }
            });
        }

        // Start Duel Arena Combat Button
        if (btnTriggerDuel) {
            btnTriggerDuel.addEventListener("click", () => {
                if (!ws || ws.readyState !== WebSocket.OPEN) {
                    alert("Connecting to server arena, please wait...");
                    return;
                }
                const arenaTab = document.querySelector('[data-tab="arena-view"]');
                if (arenaTab) arenaTab.click();

                appendSystemNotice("⚔️ Initiating live 3-tier adversarial duel...");
                ws.send(JSON.stringify({
                    action: "start_duel",
                    project: currentProject,
                    rounds: 3,
                    model: getSelectedModel()
                }));
            });
        }
    }

    // =========================================================================
    // 6. CHAOS CONSOLE INTERACTIVE ATTACKS
    // =========================================================================

    let latestDiffText = "";

    function renderDiff(diffText) {
        latestDiffText = diffText || "";
        const diffDisplay = document.getElementById("diff-display");
        const diffBadge = document.getElementById("diff-status-badge");
        if (!diffDisplay) return;

        if (!diffText || diffText.trim().startsWith("# No patches")) {
            diffDisplay.innerHTML = `
                <div class="diff-empty-state">
                    <span class="empty-icon">🛡️</span>
                    <p>No patches applied yet. Run an attack in the Chaos Console or start a duel to view real-time green/red code diffs.</p>
                </div>
            `;
            if (diffBadge) diffBadge.textContent = "Clean";
            return;
        }

        if (diffBadge) diffBadge.textContent = "Patched";
        const lines = diffText.split("\n");
        let html = "";
        for (const line of lines) {
            if (line.startsWith("+++") || line.startsWith("---")) {
                html += `<div class="diff-line diff-line-info">${escapeHTML(line)}</div>`;
            } else if (line.startsWith("+")) {
                html += `<div class="diff-line diff-line-add">${escapeHTML(line)}</div>`;
            } else if (line.startsWith("-")) {
                html += `<div class="diff-line diff-line-del">${escapeHTML(line)}</div>`;
            } else if (line.startsWith("@@")) {
                html += `<div class="diff-line diff-line-info">${escapeHTML(line)}</div>`;
            } else {
                html += `<div class="diff-line diff-line-context">${escapeHTML(line)}</div>`;
            }
        }
        diffDisplay.innerHTML = html;
    }

    async function loadPatchDiff(project) {
        try {
            const res = await fetch(`/api/patch-diff?project=${encodeURIComponent(project)}`);
            if (res.ok) {
                const text = await res.text();
                renderDiff(text);
            }
        } catch (e) {
            console.error("Failed to load patch diff:", e);
        }
    }

    function setupChaosConsole() {
        document.querySelectorAll(".attack-btn").forEach(btn => {
            btn.addEventListener("click", async () => {
                const vector = btn.getAttribute("data-vector");
                appendSpeechBubble("HACKER AI", `Firing manual ${vector.toUpperCase()} attack vector!`, "😈");
                
                try {
                    const res = await fetch("/api/chaos-attack", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            project: currentProject,
                            vector: vector,
                            model: getSelectedModel()
                        })
                    });
                    const data = await res.json();
                    if (data.breach) {
                        appendBreachCard(data.breach);
                        appendSpeechBubble("BUILDER AI", "Breach confirmed. Synthesizing instant defensive patch...", "🛠️");
                        if (data.patched) {
                            if (data.verified) {
                                appendSystemNotice(`✅ Patch verified (probe sealed, legitimate requests still work) and applied to ${data.file}.`);
                            } else if (data.reason === "breach_persists") {
                                appendSystemNotice(`⚠️ Patch rejected: the probe still reproduces. The patch was rolled back.`);
                            } else {
                                appendSystemNotice(`⚠️ Patch rejected: it broke or removed legitimate behaviour. The patch was rolled back.`);
                            }
                            if (data.diff) {
                                renderDiff(data.diff);
                            }
                            loadFileContent(currentProject, "app.py");
                            reloadPreview();
                        }
                    } else {
                        // One probe only: this is not a security score and must not change the shield.
                        appendSpeechBubble("HACKER AI", "This single probe did not breach the app.", "😈");
                        appendSystemNotice("ℹ️ One blocked probe is not proof of security. Run the full duel for a measured result.");
                    }
                } catch (e) {
                    console.error("Attack failed:", e);
                }
            });
        });
    }

    // =========================================================================
    // 7. UI TABS, PREVIEW TOGGLES, UTILITIES
    // =========================================================================

    function setupTabSwitching() {
        document.querySelectorAll(".tab-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
                document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
                btn.classList.add("active");
                const target = btn.getAttribute("data-tab");
                const targetEl = document.getElementById(target);
                if (targetEl) targetEl.classList.add("active");
                if (target === "diff-view" && !latestDiffText) {
                    loadPatchDiff(currentProject);
                }
            });
        });
    }

    function setupDeviceToggles() {
        document.querySelectorAll(".device-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll(".device-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                if (appPreviewFrame) appPreviewFrame.style.width = btn.getAttribute("data-width");
            });
        });

        if (btnReloadPreview) btnReloadPreview.addEventListener("click", reloadPreview);
        if (btnRefreshFiles) btnRefreshFiles.addEventListener("click", () => loadFiles(currentProject));

        if (projectSelect) {
            projectSelect.addEventListener("change", () => {
                currentProject = projectSelect.value;
                loadFiles(currentProject);
                loadFileContent(currentProject, "app.py");
                loadPatchDiff(currentProject);
            });
        }

        const btnCopyCode = document.getElementById("btn-copy-code");
        if (btnCopyCode && codeDisplay) {
            btnCopyCode.addEventListener("click", () => {
                navigator.clipboard.writeText(codeDisplay.textContent);
                alert("Code copied to clipboard!");
            });
        }

        const btnCopyDiff = document.getElementById("btn-copy-diff");
        if (btnCopyDiff) {
            btnCopyDiff.addEventListener("click", () => {
                if (!latestDiffText) {
                    alert("No diff available to copy!");
                    return;
                }
                navigator.clipboard.writeText(latestDiffText);
                alert("Patch diff copied to clipboard!");
            });
        }

        // Export ZIP Button in Studio Header
        const btnExportZip = document.getElementById("btn-export-zip-header");
        if (btnExportZip) {
            btnExportZip.addEventListener("click", () => {
                window.location.href = `/api/export-zip?project=${encodeURIComponent(currentProject)}`;
            });
        }
    }

    function escapeHTML(str) {
        if (!str) return "";
        return str.toString()
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // =========================================================================
    // 8. INITIALIZE APPLICATION
    // =========================================================================

    async function init() {
        setupAuthAndViews();
        setupModelSync();
        connectWebSocket();
        await loadModels();
        checkOllamaHealth();
        await loadProjects();
        await loadFiles(currentProject);
        await loadFileContent(currentProject, "app.py");
        await loadPatchDiff(currentProject);
        setupPromptListeners();
        setupTabSwitching();
        setupDeviceToggles();
        setupChaosConsole();
    }

    init();
});
