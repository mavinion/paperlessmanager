from typing import Optional
import requests
import logging

from src.config import PaperlessConfig
from src.models import DocumentInfo

logger = logging.getLogger(__name__)


class SafePaperlessClient:
    """
    Sicherer Wrapper für die Paperless-API.
    Unterstützt NUR Metadaten-Operationen, keine Dokumentenlöschung.
    
    Verwendet direkte REST-API mit requests.
    """
    
    def __init__(self, config: PaperlessConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {config.token}",
            "Content-Type": "application/json"
        })
        self._tags_cache: dict[str, int] = {}
        self._correspondents_cache: dict[str, int] = {}
        self._doc_types_cache: dict[str, int] = {}
    
    def connect(self):
        """Verbindung zu Paperless herstellen und Caches laden."""
        logger.debug(f"Verbinde mit {self.config.url}...")
        # Teste Verbindung
        response = self.session.get(f"{self.config.url}/api/documents/", params={"page_size": 1})
        logger.debug(f"GET /api/documents/ → {response.status_code} ({response.elapsed.total_seconds():.2f}s)")
        response.raise_for_status()
        self._load_caches()
    
    def disconnect(self):
        """Verbindung schließen."""
        self.session.close()
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
    
    def _load_caches(self):
        """Lädt Tags, Korrespondenten und Dokumenttypen in den Cache."""
        # Tags laden
        logger.debug("Lade Tags...")
        tags = self._fetch_all_pages("/api/tags/")
        for tag in tags:
            self._tags_cache[tag["name"].lower()] = tag["id"]
        logger.debug(f"  → {len(tags)} Tags geladen")
        
        # Korrespondenten laden
        logger.debug("Lade Korrespondenten...")
        correspondents = self._fetch_all_pages("/api/correspondents/")
        for corr in correspondents:
            self._correspondents_cache[corr["name"].lower()] = corr["id"]
        logger.debug(f"  → {len(correspondents)} Korrespondenten geladen")
        
        # Dokumenttypen laden
        logger.debug("Lade Dokumenttypen...")
        doc_types = self._fetch_all_pages("/api/document_types/")
        for dt in doc_types:
            self._doc_types_cache[dt["name"].lower()] = dt["id"]
        logger.debug(f"  → {len(doc_types)} Dokumenttypen geladen")
    
    def _fetch_all_pages(self, endpoint: str) -> list[dict]:
        """Alle Seiten eines Paginated-Endpoints abrufen."""
        results = []
        url = f"{self.config.url}{endpoint}"
        
        while url:
            logger.debug(f"GET {endpoint}")
            response = self.session.get(url)
            logger.debug(f"  → {response.status_code} ({response.elapsed.total_seconds():.2f}s)")
            response.raise_for_status()
            data = response.json()
            results.extend(data.get("results", []))
            url = data.get("next")
        
        return results
    
    def get_documents(
        self,
        limit: int = 100,
        offset: int = 0,
        untagged_only: bool = False
    ) -> list[DocumentInfo]:
        """Dokumente abrufen."""
        params = {
            "page_size": limit * 2 if untagged_only else limit,  # Mehr abrufen wenn Filterung nötig
            "page": (offset // limit) + 1
        }
        
        logger.debug(f"GET /api/documents/ (page_size={params['page_size']}, untagged={untagged_only})")
        response = self.session.get(
            f"{self.config.url}/api/documents/",
            params=params
        )
        logger.debug(f"  → {response.status_code} ({response.elapsed.total_seconds():.2f}s)")
        response.raise_for_status()
        data = response.json()
        
        docs = []
        for doc in data.get("results", []):
            # Clientseitig filtern wenn untagged_only
            if untagged_only and doc.get("tags"):
                continue
            
            # Tags auflösen
            tag_names = self._resolve_tags(doc.get("tags", []))
            
            # Korrespondent auflösen
            correspondent_name = self._resolve_correspondent(doc.get("correspondent"))
            
            # Dokumenttyp auflösen
            doc_type_name = self._resolve_document_type(doc.get("document_type"))
            
            docs.append(DocumentInfo(
                id=doc["id"],
                title=doc.get("title", ""),
                content_preview=(doc.get("content") or "")[:500],
                tags=tag_names,
                correspondent=correspondent_name,
                document_type=doc_type_name,
                created=doc.get("created")
            ))
            
            # Limit beachten
            if len(docs) >= limit:
                break
        
        return docs
    
    def _resolve_tags(self, tag_ids: list[int]) -> list[str]:
        """Tag-IDs zu Namen auflösen."""
        id_to_name = {v: k for k, v in self._tags_cache.items()}
        return [id_to_name.get(tid, f"Tag #{tid}") for tid in tag_ids]
    
    def _resolve_correspondent(self, corr_id: Optional[int]) -> Optional[str]:
        """Korrespondent-ID zu Name auflösen."""
        if not corr_id:
            return None
        id_to_name = {v: k for k, v in self._correspondents_cache.items()}
        return id_to_name.get(corr_id)
    
    def _resolve_document_type(self, dt_id: Optional[int]) -> Optional[str]:
        """Dokumenttyp-ID zu Name auflösen."""
        if not dt_id:
            return None
        id_to_name = {v: k for k, v in self._doc_types_cache.items()}
        return id_to_name.get(dt_id)
    
    def get_document_content(self, document_id: int) -> Optional[str]:
        """OCR-Inhalt eines Dokuments abrufen."""
        doc = self.get_document_raw(document_id)
        return doc.get("content") if doc else None
    
    def get_document_raw(self, document_id: int) -> Optional[dict]:
        """Rohes Dokument als Dict abrufen."""
        response = self.session.get(f"{self.config.url}/api/documents/{document_id}/")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    
    def get_document(self, document_id: int) -> Optional[DocumentInfo]:
        """Einzelnes Dokument abrufen."""
        doc = self.get_document_raw(document_id)
        if not doc:
            return None
        
        tag_names = self._resolve_tags(doc.get("tags", []))
        correspondent_name = self._resolve_correspondent(doc.get("correspondent"))
        doc_type_name = self._resolve_document_type(doc.get("document_type"))
        
        return DocumentInfo(
            id=doc["id"],
            title=doc.get("title", ""),
            content_preview=(doc.get("content") or "")[:2000],
            tags=tag_names,
            correspondent=correspondent_name,
            document_type=doc_type_name,
            created=doc.get("created")
        )
    
    def get_available_tags(self) -> list[str]:
        """Alle verfügbaren Tags abrufen."""
        return list(self._tags_cache.keys())
    
    def get_available_correspondents(self) -> list[str]:
        """Alle verfügbaren Korrespondenten abrufen."""
        return list(self._correspondents_cache.keys())
    
    def get_available_document_types(self) -> list[str]:
        """Alle verfügbaren Dokumenttypen abrufen."""
        return list(self._doc_types_cache.keys())
    
    def get_or_create_tag(self, tag_name: str) -> int:
        """Tag-ID abrufen oder neuen Tag erstellen."""
        tag_lower = tag_name.lower()
        if tag_lower in self._tags_cache:
            return self._tags_cache[tag_lower]
        
        # Neuen Tag erstellen
        response = self.session.post(
            f"{self.config.url}/api/tags/",
            json={"name": tag_name}
        )
        response.raise_for_status()
        new_tag = response.json()
        self._tags_cache[tag_lower] = new_tag["id"]
        return new_tag["id"]
    
    def get_or_create_correspondent(self, name: str) -> int:
        """Korrespondent-ID abrufen oder neuen erstellen."""
        name_lower = name.lower()
        if name_lower in self._correspondents_cache:
            return self._correspondents_cache[name_lower]
        
        response = self.session.post(
            f"{self.config.url}/api/correspondents/",
            json={"name": name}
        )
        response.raise_for_status()
        new_corr = response.json()
        self._correspondents_cache[name_lower] = new_corr["id"]
        return new_corr["id"]
    
    def get_or_create_document_type(self, name: str) -> int:
        """Dokumenttyp-ID abrufen oder neuen erstellen."""
        name_lower = name.lower()
        if name_lower in self._doc_types_cache:
            return self._doc_types_cache[name_lower]
        
        response = self.session.post(
            f"{self.config.url}/api/document_types/",
            json={"name": name}
        )
        response.raise_for_status()
        new_dt = response.json()
        self._doc_types_cache[name_lower] = new_dt["id"]
        return new_dt["id"]
    
    def update_document_tags(
        self,
        document_id: int,
        add_tags: list[str] = None,
        remove_tags: list[str] = None
    ) -> bool:
        """Tags eines Dokuments aktualisieren (SICHER - nur Metadaten)."""
        doc = self.get_document_raw(document_id)
        if not doc:
            return False
        
        current_tags = set(doc.get("tags", []))
        
        if add_tags:
            for tag_name in add_tags:
                tag_id = self.get_or_create_tag(tag_name)
                current_tags.add(tag_id)
        
        if remove_tags:
            for tag_name in remove_tags:
                tag_lower = tag_name.lower()
                if tag_lower in self._tags_cache:
                    current_tags.discard(self._tags_cache[tag_lower])
        
        # Update durchführen (nur Metadaten!)
        response = self.session.patch(
            f"{self.config.url}/api/documents/{document_id}/",
            json={"tags": list(current_tags)}
        )
        return response.status_code == 200
    
    def update_document_correspondent(
        self,
        document_id: int,
        correspondent_name: str
    ) -> bool:
        """Korrespondent eines Dokuments setzen (SICHER - nur Metadaten)."""
        corr_id = self.get_or_create_correspondent(correspondent_name)
        
        response = self.session.patch(
            f"{self.config.url}/api/documents/{document_id}/",
            json={"correspondent": corr_id}
        )
        return response.status_code == 200
    
    def update_document_type(
        self,
        document_id: int,
        doc_type_name: str
    ) -> bool:
        """Dokumenttyp setzen (SICHER - nur Metadaten)."""
        dt_id = self.get_or_create_document_type(doc_type_name)
        
        response = self.session.patch(
            f"{self.config.url}/api/documents/{document_id}/",
            json={"document_type": dt_id}
        )
        return response.status_code == 200
    
    def update_document_title(
        self,
        document_id: int,
        title: str
    ) -> bool:
        """Titel eines Dokuments ändern (SICHER - nur Metadaten)."""
        response = self.session.patch(
            f"{self.config.url}/api/documents/{document_id}/",
            json={"title": title}
        )
        return response.status_code == 200
    
    def search_documents(self, query: str, limit: int = 20) -> list[DocumentInfo]:
        """Volltextsuche in Dokumenten."""
        params = {
            "query": query,
            "page_size": limit
        }
        
        response = self.session.get(
            f"{self.config.url}/api/documents/",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        docs = []
        for doc in data.get("results", []):
            tag_names = self._resolve_tags(doc.get("tags", []))
            
            docs.append(DocumentInfo(
                id=doc["id"],
                title=doc.get("title", ""),
                content_preview=(doc.get("content") or "")[:300],
                tags=tag_names
            ))
        
        return docs
