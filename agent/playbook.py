"""
AEGIS Verified-Only Defense Playbook
Stores and retrieves verified defensive coding patterns to inoculate
new application code against previously identified and proven vulnerabilities.
"""

import os
import sys
import json
import time
import hashlib
from typing import List, Dict, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
DEFAULT_PLAYBOOK_DIR = os.path.join(root_dir, "playbook")


class PlaybookManager:
    def __init__(self, playbook_dir: Optional[str] = None):
        self.playbook_dir = playbook_dir or DEFAULT_PLAYBOOK_DIR
        os.makedirs(self.playbook_dir, exist_ok=True)

    def is_enabled(self) -> bool:
        """Checks if the playbook system is active via the PLAYBOOK environment variable."""
        val = os.environ.get("PLAYBOOK", "on").strip().lower()
        return val in ("1", "true", "on", "yes")

    def add_verified_entry(
        self,
        vuln_type: str,
        pattern_desc: str,
        safe_snippet: str,
        poc: Dict[str, Any],
        model: str = "qwen2.5-coder:7b"
    ) -> str:
        """
        Stores a verified defensive pattern.
        STRICT GATE: Refuses to store unverified patches.
        """
        if not poc or not poc.get("verified", False):
            raise ValueError("GATE REJECTION: Only verified defensive patches can be added to the Playbook.")

        poc_canonical = json.dumps(
            {"route": poc.get("route"), "method": poc.get("method"), "payload": str(poc.get("payload"))},
            sort_keys=True
        )
        poc_hash = hashlib.sha256(poc_canonical.encode("utf-8")).hexdigest()[:12]
        
        entry_id = f"pb_{int(time.time())}_{poc_hash[:6]}"
        entry_data = {
            "id": entry_id,
            "vuln_type": vuln_type,
            "pattern_desc": pattern_desc,
            "safe_snippet": safe_snippet.strip(),
            "poc_hash": poc_hash,
            "model": model,
            "timestamp": time.time(),
            "enabled": True
        }

        file_path = os.path.join(self.playbook_dir, f"{entry_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(entry_data, f, indent=2)

        return entry_id

    def list_entries(self, include_disabled: bool = True) -> List[Dict[str, Any]]:
        """Lists stored playbook entries."""
        entries = []
        if not os.path.exists(self.playbook_dir):
            return entries

        for fname in os.listdir(self.playbook_dir):
            if fname.endswith(".json") and fname.startswith("pb_"):
                fpath = os.path.join(self.playbook_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if include_disabled or data.get("enabled", True):
                            entries.append(data)
                except Exception:
                    continue

        entries.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return entries

    def set_entry_enabled(self, entry_id: str, enabled: bool) -> bool:
        """Enables or disables a playbook entry."""
        file_path = os.path.join(self.playbook_dir, f"{entry_id}.json")
        if not os.path.exists(file_path):
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["enabled"] = enabled
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False

    def delete_entry(self, entry_id: str) -> bool:
        """Deletes a playbook entry permanently."""
        file_path = os.path.join(self.playbook_dir, f"{entry_id}.json")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                return True
            except Exception:
                return False
        return False

    def get_relevant_entries(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Retrieves top-k relevant verified entries based on keyword matching.
        Returns empty list if PLAYBOOK=off or if entries are disabled.
        """
        if not self.is_enabled():
            return []

        active_entries = self.list_entries(include_disabled=False)
        if not active_entries:
            return []

        query_tokens = set(query.lower().replace("_", " ").split())
        scored = []

        for entry in active_entries:
            score = 0
            text = f"{entry.get('vuln_type', '')} {entry.get('pattern_desc', '')}".lower()
            for token in query_tokens:
                if len(token) > 2 and token in text:
                    score += 1
            if score > 0 or not query_tokens:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    def format_playbook_for_prompt(self, entries: List[Dict[str, Any]]) -> str:
        """Formats entries into concise defensive architectural constraints for the LLM."""
        if not entries:
            return ""

        lines = ["\nVERIFIED DEFENSE PLAYBOOK RULES (Inoculate against proven failure patterns):"]
        for idx, e in enumerate(entries, start=1):
            lines.append(f"{idx}. Vulnerability Pattern: {e.get('vuln_type')}")
            lines.append(f"   Defense Guideline: {e.get('pattern_desc')}")
            if e.get("safe_snippet"):
                snippet_preview = e.get("safe_snippet")[:200].replace("\n", " ")
                lines.append(f"   Safe Reference: {snippet_preview}")
        lines.append("")
        return "\n".join(lines)


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    manager = PlaybookManager()
    args = sys.argv[1:]

    if not args or args[0] == "list":
        entries = manager.list_entries(include_disabled=True)
        print(f"\n📚 AEGIS PLAYBOOK ENTRIES ({len(entries)} total):")
        print("-" * 75)
        for e in entries:
            status = "ENABLED" if e.get("enabled", True) else "DISABLED"
            print(f"[{status}] {e.get('id')} - {e.get('vuln_type')}: {e.get('pattern_desc')[:50]}")
        print("-" * 75)
    elif args[0] == "disable" and len(args) > 1:
        success = manager.set_entry_enabled(args[1], False)
        print(f"Entry {args[1]} disabled: {success}")
    elif args[0] == "enable" and len(args) > 1:
        success = manager.set_entry_enabled(args[1], True)
        print(f"Entry {args[1]} enabled: {success}")
    elif args[0] == "delete" and len(args) > 1:
        success = manager.delete_entry(args[1])
        print(f"Entry {args[1]} deleted: {success}")
    else:
        print("Usage: python agent/playbook.py [list|disable <id>|enable <id>|delete <id>]")


if __name__ == "__main__":
    main()
