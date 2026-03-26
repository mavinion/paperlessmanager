from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TagAction(BaseModel):
    """Aktion für einen Tag."""
    tag: str
    action: str  # "add" oder "remove"
    is_new: bool = False  # True wenn Tag erst erstellt werden muss
    confidence: float = 0.0


class MetadataSuggestion(BaseModel):
    """Einzelner Metadaten-Vorschlag."""
    field: str  # "correspondent", "document_type", "title"
    current_value: Optional[str] = None
    suggested_value: Optional[str] = None
    is_new: bool = False  # True wenn erst erstellt werden muss
    confidence: float = 0.0


class AnalysisResult(BaseModel):
    """Ergebnis einer KI-Dokumentenanalyse."""
    document_id: int
    document_title: str = ""
    
    # Tag-Aktionen (add/remove)
    tag_actions: list[TagAction] = []
    
    # Metadaten-Vorschläge
    correspondent_suggestion: Optional[MetadataSuggestion] = None
    document_type_suggestion: Optional[MetadataSuggestion] = None
    title_suggestion: Optional[MetadataSuggestion] = None
    
    # Zusätzliche Infos
    extracted_date: Optional[str] = None
    overall_confidence: float = 0.0
    reasoning: str = ""
    
    # Legacy-Kompatibilität
    @property
    def suggested_tags(self) -> list[str]:
        return [ta.tag for ta in self.tag_actions if ta.action == "add"]
    
    @property
    def suggested_correspondent(self) -> Optional[str]:
        return self.correspondent_suggestion.suggested_value if self.correspondent_suggestion else None
    
    @property
    def suggested_document_type(self) -> Optional[str]:
        return self.document_type_suggestion.suggested_value if self.document_type_suggestion else None
    
    @property
    def suggested_title(self) -> Optional[str]:
        return self.title_suggestion.suggested_value if self.title_suggestion else None
    
    @property
    def confidence(self) -> float:
        return self.overall_confidence


class ChangeLog(BaseModel):
    """Protokoll einer durchgeführten Änderung."""
    document_id: int
    timestamp: datetime
    field: str
    action: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    confidence: float = 0.0
    applied: bool = False


class DocumentInfo(BaseModel):
    """Vereinfachte Dokument-Infos für die Anzeige."""
    id: int
    title: str
    content_preview: str = ""
    tags: list[str] = []
    correspondent: Optional[str] = None
    document_type: Optional[str] = None
    created: Optional[datetime] = None


class ReviewedTracker:
    """Trackt bereits verarbeitete Dokumente."""
    
    def __init__(self, filepath: str = "reviewed_ids.yaml"):
        self.filepath = filepath
        self.reviewed_ids: set[int] = set()
        self._load()
    
    def _load(self):
        """Gespeicherte IDs laden."""
        import yaml
        from pathlib import Path
        path = Path(self.filepath)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            self.reviewed_ids = set(data)
    
    def save(self):
        """IDs speichern."""
        import yaml
        from pathlib import Path
        with open(self.filepath, "w", encoding="utf-8") as f:
            yaml.dump(sorted(self.reviewed_ids), f, default_flow_style=False)
    
    def add(self, ids: list[int]):
        """IDs hinzufügen."""
        self.reviewed_ids.update(ids)
    
    def is_reviewed(self, doc_id: int) -> bool:
        """Prüfen ob bereits verarbeitet."""
        return doc_id in self.reviewed_ids
    
    def reset(self):
        """Alle Einträge löschen."""
        self.reviewed_ids.clear()
    
    def __len__(self):
        return len(self.reviewed_ids)
