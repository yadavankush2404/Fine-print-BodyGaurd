
document.getElementById("analyzeBtn").addEventListener("click", async () => {
  // UI Updates
  document.getElementById("start-screen").style.display = "none";
  document.getElementById("loading").style.display = "block";

  let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  // 1. Scrape Text
  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    function: getPageText,
  }, async (results) => {
    if (results && results[0]) {
      try {
        // 2. Call Backend
        const response = await fetch("http://127.0.0.1:8000/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: tab.url, text: results[0].result })
        });

        const data = await response.json();
        displayReport(data);

      } catch (error) {
        document.getElementById("loading").innerHTML = `<span style='color:red'>Error: Backend not running?</span>`;
        console.error(error);
      }
    }
  });
});

function getPageText() { return document.body.innerText; }

function displayReport(data) {
  document.getElementById("loading").style.display = "none";
  document.getElementById("results-container").style.display = "block";
  
  const score = data.safety_score;
  const analysis = data.analysis;

  // 1. Update Score Badge
  const badge = document.getElementById("score-badge");
  const text = document.getElementById("score-text");
  
  badge.innerText = score + "%";
  text.innerText = score > 80 ? "Excellent" : (score > 50 ? "Caution" : "Critical Risk");
  
  // Color logic
  badge.className = "score-badge " + (score > 80 ? "bg-green" : (score > 50 ? "bg-orange" : "bg-red"));

  // 2. Build Fault List
  const faultsList = document.getElementById("faults-list");
  faultsList.innerHTML = "<h2>⚠️ Detected Risks</h2>";
  
  let riskCount = 0;

  for (const [question, answer] of Object.entries(analysis)) {
    if (answer.toUpperCase().includes("YES")) {
      riskCount++;
      
      // CLEANING LOGIC FIXED:
      // Remove "YES", dots, colons, dashes, and whitespace from the start
      let cleanExplanation = answer.replace(/^YES[\.\:\-\s]*/i, "").trim();
      
      // If the explanation is empty or just dots, add a fallback
      if (cleanExplanation.length < 5 || cleanExplanation === "...") {
        cleanExplanation = "The policy contains this clause, but the AI did not provide a specific quote.";
      }

      const card = document.createElement("div");
      card.className = "fault-card";
      card.innerHTML = `
        <div class="fault-title">${simplifyQuestion(question)}</div>
        <div class="fault-desc">"${cleanExplanation}"</div>
      `;
      
      faultsList.appendChild(card);
    }
  }

  if (riskCount === 0) {
    document.getElementById("faults-list").style.display = "none";
    document.getElementById("safe-message").style.display = "block";
  }
}

// Helper to make the titles shorter and punchier
function simplifyQuestion(question) {
  if (question.includes("sell my data")) return "DATA SELLING DETECTED";
  if (question.includes("arbitration")) return "FORCED ARBITRATION";
  if (question.includes("class action")) return "NO CLASS ACTION SUITS";
  if (question.includes("license to use")) return "CONTENT OWNERSHIP GRAB";
  if (question.includes("track my location")) return "SPYING / TRACKING";
  if (question.includes("change the terms")) return "UNILATERAL CHANGES";
  return "UNSAFE POLICY CLAUSE";
}