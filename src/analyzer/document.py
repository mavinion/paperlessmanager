from datetime import datetime
from typing import Optional
import yaml
from pathlib import Path

from src.config import AppConfig
from src.paperless.client import SafePaperlessClient
from src.ai.provider import create_ai_provider, AIProvider
from src.models import AnalysisResult, ChangeLog, DocumentInfo, TagAction, MetadataSuggestion


class DocumentAnalyzer:
    """
    Hauptklasse für die KI-gestützte Dokumentenanalyse.
    Koordiniert Paperless-Client und KI-Provider.
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.paperless = SafePaperlessClient(config.paperless)
        self.ai_provider: AIProvider = create_ai_provider(config.ai)
        self.changes_log: list[ChangeLog] = []
    
    def __enter__(self):
        self.paperless.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.paperless.disconnect()
    
    def analyze_document(
        self,
        document_id: int
    ) -> Optional[AnalysisResult]:
        """
        Einzelnes Dokument analysieren.
        Gibt detaillierte Vorschläge zurück (ohne Änderungen).
        """
        # Dokument abrufen
        doc = self.paperless.get_document(document_id)
        if not doc:
            return None
        
        # Verfügbare Metadaten abrufen
        available_tags = self.paperless.get_available_tags()
        available_correspondents = self.paperless.get_available_correspondents()
        available_doc_types = self.paperless.get_available_document_types()
        
        # KI-Analyse durchführen
        result = self.ai_provider.analyze_document(
            document_content=doc.content_preview,
            document_title=doc.title,
            current_tags=doc.tags,
            current_correspondent=doc.correspondent,
            current_document_type=doc.document_type,
            available_tags=available_tags,
            available_correspondents=available_correspondents,
            available_document_types=available_doc_types,
            language=self.config.analysis.language
        )
        
        result.document_id = document_id
        return result
    
    def get_document_with_result(self, document_id: int) -> tuple[Optional[DocumentInfo], Optional[AnalysisResult]]:
        """
        Dokument und Analyseergebnis zusammen abrufen.
        Für die interaktive Anzeige.
        """
        doc = self.paperless.get_document(document_id)
        if not doc:
            return None, None
        
        result = self.analyze_document(document_id)
        return doc, result
    
    def apply_result(
        self,
        result: AnalysisResult,
        selected_tag_actions: list[TagAction] = None,
        apply_correspondent: bool = False,
        apply_document_type: bool = False,
        apply_title: bool = False
    ) -> list[ChangeLog]:
        """
        Ausgewählte Änderungen anwenden.
        Gibt Liste der durchgeführten Änderungen zurück.
        """
        changes = []
        timestamp = datetime.now()
        
        # Tags anwenden
        if selected_tag_actions is None:
            selected_tag_actions = result.tag_actions
        
        for tag_action in selected_tag_actions:
            if tag_action.action == "add":
                success = self.paperless.update_document_tags(
                    document_id=result.document_id,
                    add_tags=[tag_action.tag]
                )
                if success:
                    changes.append(ChangeLog(
                        document_id=result.document_id,
                        timestamp=timestamp,
                        field="tags",
                        action="add",
                        new_value=tag_action.tag,
                        confidence=tag_action.confidence,
                        applied=True
                    ))
            
            elif tag_action.action == "remove":
                success = self.paperless.update_document_tags(
                    document_id=result.document_id,
                    remove_tags=[tag_action.tag]
                )
                if success:
                    changes.append(ChangeLog(
                        document_id=result.document_id,
                        timestamp=timestamp,
                        field="tags",
                        action="remove",
                        old_value=tag_action.tag,
                        confidence=tag_action.confidence,
                        applied=True
                    ))
        
        # Korrespondent anwenden
        if apply_correspondent and result.correspondent_suggestion:
            success = self.paperless.update_document_correspondent(
                document_id=result.document_id,
                correspondent_name=result.correspondent_suggestion.suggested_value
            )
            if success:
                changes.append(ChangeLog(
                    document_id=result.document_id,
                    timestamp=timestamp,
                    field="correspondent",
                    action="set",
                    old_value=result.correspondent_suggestion.current_value,
                    new_value=result.correspondent_suggestion.suggested_value,
                    confidence=result.correspondent_suggestion.confidence,
                    applied=True
                ))
        
        # Dokumenttyp anwenden
        if apply_document_type and result.document_type_suggestion:
            success = self.paperless.update_document_type(
                document_id=result.document_id,
                doc_type_name=result.document_type_suggestion.suggested_value
            )
            if success:
                changes.append(ChangeLog(
                    document_id=result.document_id,
                    timestamp=timestamp,
                    field="document_type",
                    action="set",
                    old_value=result.document_type_suggestion.current_value,
                    new_value=result.document_type_suggestion.suggested_value,
                    confidence=result.document_type_suggestion.confidence,
                    applied=True
                ))
        
        # Titel anwenden
        if apply_title and result.title_suggestion:
            success = self.paperless.update_document_title(
                document_id=result.document_id,
                title=result.title_suggestion.suggested_value
            )
            if success:
                changes.append(ChangeLog(
                    document_id=result.document_id,
                    timestamp=timestamp,
                    field="title",
                    action="set",
                    old_value=result.title_suggestion.current_value,
                    new_value=result.title_suggestion.suggested_value,
                    confidence=result.title_suggestion.confidence,
                    applied=True
                ))
        
        self.changes_log.extend(changes)
        return changes
    
    def get_documents_for_review(
        self,
        limit: int = 100,
        untagged_only: bool = False,
        all_docs: bool = False,
        skip_reviewed: set[int] = None
    ) -> list[DocumentInfo]:
        """
        Dokumente für die Review abrufen.
        Wenn skip_reviewed gesetzt ist, werden bereits verarbeitete Dokumente
        übersprungen und so lange weitere geholt bis limit erreicht ist.
        """
        if all_docs or skip_reviewed is None:
            # Kein Skip-Filter
            if untagged_only:
                return self.paperless.get_documents(limit=limit, untagged_only=True)
            return self.paperless.get_documents(limit=limit)
        
        # Mit Skip-Filter: Dokumente in Batches holen bis limit erreicht
        result = []
        offset = 0
        batch_size = max(limit * 2, 20)
        max_fetch = limit * 10  # Sicherheitslimit
        
        while len(result) < limit and offset < max_fetch:
            if untagged_only:
                batch = self.paperless.get_documents(
                    limit=batch_size, offset=offset, untagged_only=True
                )
            else:
                batch = self.paperless.get_documents(
                    limit=batch_size, offset=offset
                )
            
            if not batch:
                break
            
            for doc in batch:
                if doc.id not in skip_reviewed:
                    result.append(doc)
                    if len(result) >= limit:
                        break
            
            offset += batch_size
        
        return result
    
    def search(self, query: str, limit: int = 20) -> list[DocumentInfo]:
        """Natürliche Suche in Dokumenten."""
        return self.paperless.search_documents(query, limit)
    
    def save_changes_log(self, filepath: str = "changes_log.yaml"):
        """Änderungsprotokoll speichern."""
        # Bestehende Logs laden und anhängen
        existing = []
        if Path(filepath).exists():
            with open(filepath, "r", encoding="utf-8") as f:
                existing = yaml.safe_load(f) or []
        
        new_entries = []
        for change in self.changes_log:
            new_entries.append({
                "document_id": change.document_id,
                "timestamp": change.timestamp.isoformat(),
                "field": change.field,
                "action": change.action,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "confidence": change.confidence,
                "applied": change.applied
            })
        
        all_entries = existing + new_entries
        
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(all_entries, f, default_flow_style=False, allow_unicode=True)
    
    def load_changes_log(self, filepath: str = "changes_log.yaml"):
        """Änderungsprotokoll laden."""
        path = Path(filepath)
        if not path.exists():
            return
        
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        
        self.changes_log = [
            ChangeLog(
                document_id=item["document_id"],
                timestamp=datetime.fromisoformat(item["timestamp"]),
                field=item["field"],
                action=item["action"],
                old_value=item.get("old_value"),
                new_value=item.get("new_value"),
                confidence=item.get("confidence", 0.0),
                applied=item.get("applied", False)
            )
            for item in data
        ]
