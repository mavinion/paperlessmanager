from abc import ABC, abstractmethod
import json
import os
import logging
import time
from typing import Optional

from src.config import AIConfig
from src.models import AnalysisResult, TagAction, MetadataSuggestion

logger = logging.getLogger(__name__)


class AIProvider(ABC):
    """Abstrakte Basisklasse für KI-Provider."""
    
    @abstractmethod
    def analyze_document(
        self,
        document_content: str,
        document_title: str,
        current_tags: list[str],
        current_correspondent: Optional[str],
        current_document_type: Optional[str],
        available_tags: list[str],
        available_correspondents: list[str],
        available_document_types: list[str],
        language: str = "de"
    ) -> AnalysisResult:
        pass


class LiteLLMProvider(AIProvider):
    """
    KI-Provider mit LiteLLM.
    Unterstützt viele Provider: Ollama, OpenAI, Anthropic, Azure, Gemini, etc.
    """
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.model = self._get_model_string()
    
    def _get_model_string(self) -> str:
        """Erstellt den LiteLLM Model-String."""
        # Flexible Model-Konfiguration (empfohlen)
        if self.config.model and "/" in self.config.model:
            # ollama/ -> ollama_chat/ für bessere thinking-Modell Unterstützung
            if self.config.model.startswith("ollama/"):
                return self.config.model.replace("ollama/", "ollama_chat/", 1)
            return self.config.model
        
        # Legacy-Unterstützung
        if self.config.provider == "openai":
            return f"openai/{self.config.openai.model}"
        elif self.config.provider == "ollama":
            return f"ollama_chat/{self.config.ollama.model}"
        else:
            # Fallback: Verwende model direkt
            return self.config.model
    
    def _get_system_prompt(self, language: str) -> str:
        """System-Prompt basierend auf Sprache."""
        if language == "de":
            return """Du bist ein präziser Dokumentenmanagement-Assistent.
Analysiere Dokumente und extrahiere Metadaten.

KORRESPONDENT (Absender):
- Derjenige, der das Dokument ERSTELLT und VERSENDET hat
- Typische Positionen: Briefkopf oben, "Von:", "Ihr:", Unterschrift, Firmenstempel
- NICHT der Empfänger ("An:", "Herr/Frau...", "Sehr geehrte/r...")
- NICHT die Adresse des Empfängers

DOKUMENTTYP-REGELN:
- Rechnung: Jemand will Geld (Rechnungsnummer, Betrag, Fälligkeit)
- Bescheid: Behörde entscheidet (Finanzamt, Rentenversicherung)
- Vertrag: Vereinbarung zwischen Parteien
- Schreiben: Allgemeine Mitteilung ohne Zahlungsaufforderung

TAG-REGELN:
- Maximal 3 Tags, nur die relevantesten
- Tags basieren auf INHALT, nicht nur Titel
- Wenn ein Tag nicht passt, entfernen statt hinzufügen

Antworte AUSSCHLIESSLICH mit gültigem JSON. Denke nicht lange nach - antworte direkt."""
        else:
            return """You are a precise document management assistant.
Analyze documents and extract metadata.

CORRESPONDENT (Sender):
- The entity that CREATED and SENT the document
- Typical positions: Letterhead at top, "From:", "Sincerely,", signature, company stamp
- NOT the recipient ("To:", "Dear Mr/Mrs...", "Dear Sir/Madam...")
- NOT the recipient's address

DOCUMENT TYPE RULES:
- Invoice: Someone wants money (invoice number, amount, due date)
- Official notice: Authority decides (tax office, pension office)
- Contract: Agreement between parties
- Letter: General communication without payment request

TAG RULES:
- Maximum 3 tags, only the most relevant
- Tags based on CONTENT, not just title
- If a tag doesn't fit, remove instead of add

Respond ONLY with valid JSON. Do not think - respond directly."""
    
    def _get_user_prompt(
        self,
        document_content: str,
        document_title: str,
        current_tags: list[str],
        current_correspondent: Optional[str],
        current_document_type: Optional[str],
        available_tags: list[str],
        available_correspondents: list[str],
        available_document_types: list[str],
        language: str
    ) -> str:
        """User-Prompt für die Dokumentenanalyse."""
        
        # Content begrenzen (Token sparen)
        content_preview = document_content[:3000] if document_content else ""
        
        current_info = []
        if current_tags:
            current_info.append(f"Aktuelle Tags: {', '.join(current_tags)}")
        else:
            current_info.append("Aktuelle Tags: KEINE")
        
        if current_correspondent:
            current_info.append(f"Aktueller Korrespondent: {current_correspondent}")
        else:
            current_info.append("Aktueller Korrespondent: KEINER")
        
        if current_document_type:
            current_info.append(f"Aktueller Dokumenttyp: {current_document_type}")
        else:
            current_info.append("Aktueller Dokumenttyp: KEINER")
        
        current_block = "\n".join(current_info)
        
        if language == "de":
            return f"""Analysiere dieses Dokument Schritt für Schritt.

TITEL: {document_title}

INHALT:
{content_preview}

{current_block}

VERFÜGBARE EINTRÄGE:
- Tags: {', '.join(available_tags[:50]) if available_tags else 'Keine'}
- Korrespondenten: {', '.join(available_correspondents[:30]) if available_correspondents else 'Keine'}
- Dokumenttypen: {', '.join(available_document_types[:20]) if available_document_types else 'Keine'}

SCHRITT 1: ABSENDER identifizieren
Frage: Wer hat dieses Dokument ERSTELLT/VERSENDET?
- Suche im Briefkopf OBEN (Firmenname, Logo)
- Suche bei "Von:", "Ihr:", "Mit freundlichen Grüßen"
- NICHT der Empfänger (steht bei "An:" oder nach "Sehr geehrte/r")

SCHRITT 2: DOKUMENTTYP bestimmen
- Rechnung: Enthält Rechnungsnummer, Betrag, Fälligkeit
- Bescheid: Kommt von einer Behörde (Finanzamt, Rentenversicherung)
- Vertrag: Unterschrieben von beiden Parteien
- Schreiben: Sonstiges

SCHRITT 3: TAGS vorschlagen
- Basierend auf INHALT, nicht nur Titel
- Maximal 3 Tags
- Entferne Tags die nicht passen

SCHRITT 4: TITEL verbessern (nur wenn aktuell schlecht)

Gib JSON zurück:
{{
  "tag_actions": [
    {{"tag": "tagname", "action": "add", "is_new": false, "confidence": 0.9}},
    {{"tag": "falscher_tag", "action": "remove", "is_new": false, "confidence": 0.8}}
  ],
  "correspondent": {{
    "suggested_value": "Name des Absenders oder null",
    "is_new": false,
    "confidence": 0.9
  }},
  "document_type": {{
    "suggested_value": "Typ oder null",
    "is_new": false,
    "confidence": 0.9
  }},
  "title": {{
    "suggested_value": "Verbesserter Titel oder null",
    "is_new": false,
    "confidence": 0.9
  }},
  "extracted_date": "YYYY-MM-DD oder null",
  "overall_confidence": 0.85,
  "reasoning": "Begründung mit Textstellen"
}}"""
        else:
            return f"""Analyze this document step by step.

TITLE: {document_title}

CONTENT:
{content_preview}

{current_block}

AVAILABLE ENTRIES:
- Tags: {', '.join(available_tags[:50]) if available_tags else 'None'}
- Correspondents: {', '.join(available_correspondents[:30]) if available_correspondents else 'None'}
- Document types: {', '.join(available_document_types[:20]) if available_document_types else 'None'}

STEP 1: Identify SENDER
Question: Who CREATED/SENT this document?
- Look in letterhead at TOP (company name, logo)
- Look at "From:", "Sincerely,", signature
- NOT the recipient (at "To:" or after "Dear...")

STEP 2: Determine DOCUMENT TYPE
- Invoice: Contains invoice number, amount, due date
- Official notice: From authority (tax office, pension office)
- Contract: Signed by both parties
- Letter: General communication without payment request

STEP 3: Suggest TAGS
- Based on CONTENT, not just title
- Maximum 3 tags
- Remove tags that don't fit

STEP 4: Improve TITLE (only if current is bad)

Return JSON:
{{
  "tag_actions": [
    {{"tag": "tagname", "action": "add", "is_new": false, "confidence": 0.9}},
    {{"tag": "wrong_tag", "action": "remove", "is_new": false, "confidence": 0.8}}
  ],
  "correspondent": {{
    "suggested_value": "Sender name or null",
    "is_new": false,
    "confidence": 0.9
  }},
  "document_type": {{
    "suggested_value": "Type or null",
    "is_new": false,
    "confidence": 0.9
  }},
  "title": {{
    "suggested_value": "Improved title or null",
    "is_new": false,
    "confidence": 0.9
  }},
  "extracted_date": "YYYY-MM-DD or null",
  "overall_confidence": 0.85,
  "reasoning": "Reasoning with text passages"
}}"""
    
    def _configure_provider(self):
        """Provider-spezifische Konfiguration setzen."""
        model_lower = self.model.lower()
        
        # OpenAI (inkl. Azure, Custom OpenAI-kompatible APIs)
        if model_lower.startswith("openai/"):
            api_key = self.config.api_key or self.config.openai.api_key
            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key
            
            # Custom API Base URL
            if self.config.api_base:
                os.environ["OPENAI_API_BASE"] = self.config.api_base
                logger.debug(f"OpenAI Base URL: {self.config.api_base}")
        
        # Anthropic (Claude)
        elif model_lower.startswith("anthropic/"):
            if self.config.api_key:
                os.environ["ANTHROPIC_API_KEY"] = self.config.api_key
                logger.debug("Anthropic API Key gesetzt")
        
        # Ollama
        elif model_lower.startswith("ollama/") or model_lower.startswith("ollama_chat/"):
            base_url = self.config.api_base or self.config.ollama.url
            base_url = base_url.rstrip("/")
            # Remove trailing API path to get clean base URL for LiteLLM
            for suffix in ["/api/generate", "/api/chat", "/api"]:
                if base_url.endswith(suffix):
                    base_url = base_url[:-len(suffix)]
                    break
            base_url = base_url.rstrip("/")
            os.environ["OLLAMA_API_BASE"] = base_url
            logger.debug(f"Ollama Base URL: {base_url}")
        
        # Azure OpenAI
        elif model_lower.startswith("azure/"):
            if self.config.api_key:
                os.environ["AZURE_API_KEY"] = self.config.api_key
            if self.config.api_base:
                os.environ["AZURE_API_BASE"] = self.config.api_base
            if self.config.api_version:
                os.environ["AZURE_API_VERSION"] = self.config.api_version
            logger.debug(f"Azure konfiguriert")
        
        # Google Gemini
        elif model_lower.startswith("gemini/"):
            if self.config.api_key:
                os.environ["GEMINI_API_KEY"] = self.config.api_key
                logger.debug("Gemini API Key gesetzt")
        
        # Fallback: Custom API mit api_base
        elif self.config.api_base:
            os.environ["OPENAI_API_BASE"] = self.config.api_base
            if self.config.api_key:
                os.environ["OPENAI_API_KEY"] = self.config.api_key
            logger.debug(f"Custom API Base: {self.config.api_base}")
    
    def analyze_document(
        self,
        document_content: str,
        document_title: str,
        current_tags: list[str],
        current_correspondent: Optional[str],
        current_document_type: Optional[str],
        available_tags: list[str],
        available_correspondents: list[str],
        available_document_types: list[str],
        language: str = "de"
    ) -> AnalysisResult:
        """Dokument mit KI analysieren."""
        import litellm
        
        # Provider-spezifische Konfiguration
        self._configure_provider()
        
        logger.debug(f"KI-Provider: {self.model}")
        
        system_prompt = self._get_system_prompt(language)
        user_prompt = self._get_user_prompt(
            document_content,
            document_title,
            current_tags,
            current_correspondent,
            current_document_type,
            available_tags,
            available_correspondents,
            available_document_types,
            language
        )
        
        logger.debug(f"Prompt-Größe: {len(user_prompt)} Zeichen")
        
        try:
            start_time = time.time()
            response = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=4096,
                stream=False
            )
            elapsed = time.time() - start_time
            
            response_text = response.choices[0].message.content or ""
            
            # Logge die rohe KI-Antwort für Debugging
            logger.debug(f"KI-Response ({elapsed:.1f}s, {len(response_text)} Zeichen)")
            if response_text:
                logger.debug(f"KI-Response (raw): {response_text[:500]}")
            else:
                # Prüfe ob reasoning_content vorhanden (manche Modelle nutzen das)
                reasoning = getattr(response.choices[0].message, "reasoning_content", None)
                if reasoning:
                    logger.debug(f"KI-Response (reasoning only, {len(reasoning)} chars): {reasoning[:500]}")
                    response_text = reasoning
                else:
                    # Prüfe die komplette Response-Struktur
                    logger.debug(f"KI-Response ist leer. Full response: {response}")
            
            if not response_text or not response_text.strip():
                return AnalysisResult(
                    document_id=0,
                    overall_confidence=0.0,
                    reasoning="KI hat eine leere Antwort zurückgegeben. Prüfe ob das Modell existiert und antwortet."
                )
            
            # JSON parsen (mit Fehlerbehandlung)
            json_text = response_text.strip()
            
            # Markdown-Code-Blöcke entfernen
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0].strip()
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0].strip()
            
            # JSON aus Text extrahieren (falls Text davor/danach ist)
            import re
            json_match = re.search(r'\{[\s\S]*\}', json_text)
            if json_match:
                json_text = json_match.group(0)
            
            logger.debug(f"JSON: {json_text[:200]}...")
            data = json.loads(json_text)
            
            # Tag-Aktionen parsen
            tag_actions = []
            for ta in data.get("tag_actions", []):
                tag_actions.append(TagAction(
                    tag=ta.get("tag", ""),
                    action=ta.get("action", "add"),
                    is_new=ta.get("is_new", False) or ta.get("tag", "").startswith("NEU:") or ta.get("tag", "").startswith("NEW:"),
                    confidence=ta.get("confidence", 0.5)
                ))
            
            # Korrespondent-Vorschlag parsen
            corr_data = data.get("correspondent", {})
            correspondent_suggestion = None
            if corr_data and corr_data.get("suggested_value"):
                suggested = corr_data["suggested_value"]
                is_new = corr_data.get("is_new", False) or suggested.startswith("NEU:") or suggested.startswith("NEW:")
                # Nur vorschlagen wenn anders als aktuell
                if suggested != current_correspondent:
                    correspondent_suggestion = MetadataSuggestion(
                        field="correspondent",
                        current_value=current_correspondent,
                        suggested_value=suggested.replace("NEU:", "").replace("NEW:", "").strip() if is_new else suggested,
                        is_new=is_new,
                        confidence=corr_data.get("confidence", 0.5)
                    )
            
            # Dokumenttyp-Vorschlag parsen
            dt_data = data.get("document_type", {})
            document_type_suggestion = None
            if dt_data and dt_data.get("suggested_value"):
                suggested = dt_data["suggested_value"]
                is_new = dt_data.get("is_new", False) or suggested.startswith("NEU:") or suggested.startswith("NEW:")
                if suggested != current_document_type:
                    document_type_suggestion = MetadataSuggestion(
                        field="document_type",
                        current_value=current_document_type,
                        suggested_value=suggested.replace("NEU:", "").replace("NEW:", "").strip() if is_new else suggested,
                        is_new=is_new,
                        confidence=dt_data.get("confidence", 0.5)
                    )
            
            # Titel-Vorschlag parsen
            title_data = data.get("title", {})
            title_suggestion = None
            if title_data and title_data.get("suggested_value"):
                suggested = title_data["suggested_value"]
                if suggested != document_title:
                    title_suggestion = MetadataSuggestion(
                        field="title",
                        current_value=document_title,
                        suggested_value=suggested,
                        is_new=False,
                        confidence=title_data.get("confidence", 0.5)
                    )
            
            return AnalysisResult(
                document_id=0,
                document_title=document_title,
                tag_actions=tag_actions,
                correspondent_suggestion=correspondent_suggestion,
                document_type_suggestion=document_type_suggestion,
                title_suggestion=title_suggestion,
                extracted_date=data.get("extracted_date"),
                overall_confidence=data.get("overall_confidence", 0.0),
                reasoning=data.get("reasoning", "")
            )
        
        except json.JSONDecodeError as e:
            return AnalysisResult(
                document_id=0,
                overall_confidence=0.0,
                reasoning=f"JSON-Parsing fehlgeschlagen: {str(e)}"
            )
        except Exception as e:
            return AnalysisResult(
                document_id=0,
                overall_confidence=0.0,
                reasoning=f"KI-Fehler: {str(e)}"
            )


def create_ai_provider(config: AIConfig) -> AIProvider:
    """Factory-Funktion für KI-Provider."""
    return LiteLLMProvider(config)
