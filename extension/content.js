// content.js

// 1. Listen for messages from the Popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  
  if (request.action === "GET_TEXT") {
    sendResponse({ text: document.body.innerText });
  }

  if (request.action === "HIGHLIGHT_RISKS") {
    const badSentences = request.risks;
    highlightText(badSentences);
    sendResponse({ status: "Highlights applied" });
  }
});

// 2. The Function to Find and Highlight Text
function highlightText(sentences) {
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
    null,
    false
  );

  let node;
  const nodesToChange = [];

  // Scan the whole page
  while (node = walker.nextNode()) {
    sentences.forEach(sentence => {
      if (node.nodeValue.includes(sentence)) {
        nodesToChange.push({ node, sentence });
      }
    });
  }

  // Apply the Red Background
  nodesToChange.forEach(({ node, sentence }) => {
    const span = document.createElement("span");
    span.style.backgroundColor = "#ffcccc"; // Light red background
    span.style.border = "2px solid red";    // Red border
    span.style.color = "black";
    span.style.fontWeight = "bold";
    span.title = "⚠️ AI identified this as a risk"; // Tooltip
    
    // Replace the specific text with our styled span
    const regex = new RegExp(`(${escapeRegExp(sentence)})`, 'gi');
    const newHtml = node.nodeValue.replace(regex, `<mark style="background-color: #ff5555; color: white;">$1</mark>`);
    
    if(node.parentElement) {
        node.parentElement.style.border = "3px solid red";
        node.parentElement.title = "⚠️ Risk Detected Here";
    }
  });
}

// Helper to prevent regex errors if text has special symbols
function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}