import typer
import logging
from typing import Optional, Union, Dict, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.logging import RichHandler

from src.config import load_config
from src.analyzer.document import DocumentAnalyzer
from src.models import AnalysisResult, TagAction, ReviewedTracker

app = typer.Typer(
    name="paperless-ai",
    help="KI-gestütztes Dokumentenmanagement für Paperless-NGX"
)
console = Console()

# Globale Flags
verbose_mode = False
debug_mode = False


def setup_logging(debug: bool):
    """Logging konfigurieren."""
    level = logging.DEBUG if debug else logging.WARNING
    
    # Root Logger konfigurieren
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False, show_time=False)]
    )
    
    # Unsere Module auf DEBUG setzen
    logging.getLogger("src.paperless.client").setLevel(level)
    logging.getLogger("src.ai.provider").setLevel(level)
    
    # Externe Bibliotheken auf WARNING setzen (weniger Rauschen)
    litellm_logger = logging.getLogger("litellm")
    litellm_logger.setLevel(logging.WARNING)
    litellm_logger.propagate = False
    for name in logging.root.manager.loggerDict:
        if name.startswith("litellm."):
            child = logging.getLogger(name)
            child.setLevel(logging.WARNING)
            child.propagate = False
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def log_info(message: str):
    """Info-Meldung ausgeben (verbose oder höher)."""
    if verbose_mode or debug_mode:
        console.print(f"[dim]→ {message}[/dim]")


def log_success(message: str):
    """Erfolgs-Meldung ausgeben."""
    if verbose_mode or debug_mode:
        console.print(f"[green]✓ {message}[/green]")


def log_debug(message: str):
    """Debug-Meldung ausgeben."""
    if debug_mode:
        console.print(f"[dim cyan][DEBUG] {message}[/dim cyan]")


def log_status(message: str):
    """Status-Meldung ausgeben (immer)."""
    console.print(f"[blue]{message}[/blue]")


def get_config(config_path: str = "config.yaml"):
    """Konfiguration laden mit Fehlerbehandlung."""
    try:
        return load_config(config_path)
    except Exception as e:
        console.print(f"[red]Fehler beim Laden der Konfiguration: {e}[/red]")
        console.print("[yellow]Stelle sicher, dass config.yaml existiert.[/yellow]")
        console.print("[yellow]Nutze 'paperless-ai init' um eine Beispiel-Konfiguration zu erstellen.[/yellow]")
        raise typer.Exit(1)


@app.command()
def init():
    """Erstellt eine Beispiel-Konfigurationsdatei."""
    config_path = "config.yaml"
    
    from pathlib import Path
    if Path(config_path).exists():
        if not Confirm.ask(f"[yellow]{config_path} existiert bereits. Überschreiben?[/yellow]"):
            raise typer.Abort()
    
    from src.config import AppConfig, save_config
    config = AppConfig()
    save_config(config, config_path)
    
    console.print(f"[green]✓ Konfiguration erstellt: {config_path}[/green]")
    console.print("[yellow]Bitte passe die Werte in config.yaml an.[/yellow]")


@app.command()
def reset():
    """Verarbeitete Dokumente zurücksetzen."""
    tracker = ReviewedTracker()
    count = len(tracker)
    
    if count == 0:
        console.print("[yellow]Keine verarbeiteten Dokumente vorhanden.[/yellow]")
        return
    
    if Confirm.ask(f"[yellow]{count} verarbeitete Dokumente zurücksetzen?[/yellow]"):
        tracker.reset()
        tracker.save()
        console.print("[green]✓ Zurückgesetzt.[/green]")
    else:
        console.print("[dim]Abgebrochen.[/dim]")


@app.command(name="review")
def review(
    document_id: Optional[int] = typer.Option(None, "--id", "-i", help="Einzelnes Dokument reviewen"),
    untagged: bool = typer.Option(False, "--untagged", "-u", help="Nur ungetaggte Dokumente"),
    all_docs: bool = typer.Option(False, "--all", "-a", help="Bereits verarbeitete einbeziehen"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximale Anzahl Dokumente"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Statusmeldungen anzeigen"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Debug-Ausgaben anzeigen"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Pfad zur Konfiguration")
):
    """Interaktiv Dokumente durchgehen und Metadaten prüfen."""
    global verbose_mode, debug_mode
    verbose_mode = verbose
    debug_mode = debug
    setup_logging(debug)
    
    config = get_config(config_path)
    
    with DocumentAnalyzer(config) as analyzer:
        log_info(f"Verbinde mit Paperless ({config.paperless.url})...")
        log_success("Verbunden.")
        
        # Review-Tracker laden
        tracker = ReviewedTracker()
        
        if document_id:
            # Einzelnes Dokument
            log_info(f"Lade Dokument #{document_id}...")
            docs = [analyzer.paperless.get_document(document_id)]
            docs = [d for d in docs if d]
        else:
            # Liste von Dokumenten
            skip = None if all_docs else tracker.reviewed_ids
            log_info("Lade Dokumente...")
            docs = analyzer.get_documents_for_review(
                limit=limit,
                untagged_only=untagged,
                all_docs=all_docs,
                skip_reviewed=skip
            )
        
        if not docs:
            if not all_docs and len(tracker) > 0:
                console.print("[yellow]Keine neuen Dokumente gefunden. Nutze --all um bereits verarbeitete erneut anzuzeigen.[/yellow]")
            else:
                console.print("[yellow]Keine Dokumente gefunden.[/yellow]")
            return
        
        log_success(f"{len(docs)} Dokumente zum Review gefunden.")
        
        for i, doc in enumerate(docs):
            console.print(f"\n[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]")
            console.print(f"[bold cyan]Dokument {i+1}/{len(docs)}: #{doc.id}[/bold cyan]")
            
            # Dokument und Analyse abrufen
            log_info(f"Analysiere Dokument #{doc.id}: \"{doc.title}\"...")
            
            doc_info, result = analyzer.get_document_with_result(doc.id)
            
            if not result:
                console.print("[red]Fehler bei der Analyse.[/red]")
                continue
            
            log_success(f"Analyse abgeschlossen (Konfidenz: {result.overall_confidence:.0%})")
            
            # Dokument-Info anzeigen
            _display_document_review(doc_info, result)
            
            # Interaktive Auswahl
            action = _interactive_review(result)
            
            if action == "quit":
                console.print("[yellow]Review beendet.[/yellow]")
                break
            elif action == "skip":
                console.print("[dim]Übersprungen.[/dim]")
                continue
            elif action == "apply_all":
                log_info("Wende alle Änderungen an...")
                changes = analyzer.apply_result(result)
                analyzer.save_changes_log()
                tracker.add([doc.id])
                tracker.save()
                log_success(f"{len(changes)} Änderungen angewendet.")
            elif isinstance(action, dict):
                # Einzelne Aktionen ausgewählt
                log_info("Wende ausgewählte Änderungen an...")
                changes = analyzer.apply_result(
                    result,
                    selected_tag_actions=action.get("tags", []),
                    apply_correspondent=action.get("correspondent", False),
                    apply_document_type=action.get("document_type", False),
                    apply_title=action.get("title", False)
                )
                analyzer.save_changes_log()
                if changes:
                    tracker.add([doc.id])
                    tracker.save()
                log_success(f"{len(changes)} Änderungen angewendet.")


def _display_document_review(doc, result: AnalysisResult):
    """Dokument-Details und KI-Vorschläge anzeigen."""
    # Dokument-Info
    console.print(f"\n[bold]Titel:[/bold] {doc.title}")
    
    if doc.content_preview:
        preview = doc.content_preview[:200].replace('\n', ' ')
        console.print(f"[dim]Inhalt: {preview}...[/dim]")
    
    # Aktuelle Metadaten
    console.print("\n[bold underline]Aktuelle Metadaten:[/bold underline]")
    console.print(f"  Tags: {', '.join(doc.tags) if doc.tags else '[dim]keine[/dim]'}")
    console.print(f"  Korrespondent: {doc.correspondent or '[dim]keiner[/dim]'}")
    console.print(f"  Dokumenttyp: {doc.document_type or '[dim]keiner[/dim]'}")
    
    # KI-Vorschläge
    console.print(f"\n[bold underline]KI-Vorschläge (Konfidenz: {result.overall_confidence:.0%}):[/bold underline]")
    
    # Tag-Aktionen
    if result.tag_actions:
        console.print("\n  [bold]Tags:[/bold]")
        for ta in result.tag_actions:
            icon = "+" if ta.action == "add" else "-"
            color = "green" if ta.action == "add" else "red"
            new_marker = " [yellow](NEU)[/yellow]" if ta.is_new else ""
            console.print(f"    [{color}]{icon} {ta.tag}{new_marker} ({ta.confidence:.0%})[/{color}]")
    
    # Korrespondent
    if result.correspondent_suggestion:
        cs = result.correspondent_suggestion
        new_marker = " [yellow](NEU)[/yellow]" if cs.is_new else ""
        console.print(f"\n  [bold]Korrespondent:[/bold]")
        console.print(f"    → {cs.suggested_value}{new_marker} ({cs.confidence:.0%})")
    
    # Dokumenttyp
    if result.document_type_suggestion:
        ds = result.document_type_suggestion
        console.print(f"\n  [bold]Dokumenttyp:[/bold]")
        console.print(f"    → {ds.suggested_value} ({ds.confidence:.0%})")
    
    # Titel
    if result.title_suggestion:
        ts = result.title_suggestion
        console.print(f"\n  [bold]Titel:[/bold]")
        console.print(f"    → {ts.suggested_value} ({ts.confidence:.0%})")
    
    # Begründung
    if result.reasoning:
        console.print(f"\n  [dim]Begründung: {result.reasoning}[/dim]")


def _interactive_review(result: AnalysisResult) -> Union[str, Dict[str, Any]]:
    """Interaktive Auswahl für Review."""
    console.print("\n[bold]Aktionen:[/bold]")
    console.print("  [A]lle Vorschläge anwenden")
    console.print("  [E]inzeln auswählen")
    console.print("  [S]kippen")
    console.print("  [Q]uit")
    
    while True:
        choice = Prompt.ask("\nAuswahl", choices=["a", "e", "s", "q"], default="e")
        
        if choice == "q":
            return "quit"
        elif choice == "s":
            return "skip"
        elif choice == "a":
            return "apply_all"
        elif choice == "e":
            return _select_individual_actions(result)


def _select_individual_actions(result: AnalysisResult) -> dict:
    """Einzelne Aktionen auswählen."""
    selected = {
        "tags": [],
        "correspondent": False,
        "document_type": False,
        "title": False
    }
    
    # Tags auswählen
    if result.tag_actions:
        console.print("\n[bold]Tags auswählen:[/bold]")
        for ta in result.tag_actions:
            icon = "+" if ta.action == "add" else "-"
            default = "y" if ta.confidence >= 0.8 else "n"
            choice = Prompt.ask(
                f"  {icon} {ta.tag} ({ta.confidence:.0%})",
                choices=["y", "n"],
                default=default
            )
            if choice == "y":
                selected["tags"].append(ta)
    
    # Korrespondent
    if result.correspondent_suggestion:
        cs = result.correspondent_suggestion
        choice = Prompt.ask(
            f"\nKorrespondent auf '{cs.suggested_value}' setzen? ({cs.confidence:.0%})",
            choices=["y", "n"],
            default="y" if cs.confidence >= 0.8 else "n"
        )
        selected["correspondent"] = choice == "y"
    
    # Dokumenttyp
    if result.document_type_suggestion:
        ds = result.document_type_suggestion
        choice = Prompt.ask(
            f"\nDokumenttyp auf '{ds.suggested_value}' setzen? ({ds.confidence:.0%})",
            choices=["y", "n"],
            default="y" if ds.confidence >= 0.8 else "n"
        )
        selected["document_type"] = choice == "y"
    
    # Titel
    if result.title_suggestion:
        ts = result.title_suggestion
        choice = Prompt.ask(
            f"\nTitel auf '{ts.suggested_value}' ändern? ({ts.confidence:.0%})",
            choices=["y", "n"],
            default="n"  # Titel-Änderungen sind riskanter
        )
        selected["title"] = choice == "y"
    
    return selected


@app.command()
def analyze(
    auto: bool = typer.Option(False, "--auto", help="Automatisch anwenden (ohne Nachfrage)"),
    document_id: Optional[int] = typer.Option(None, "--id", "-i", help="Einzelnes Dokument"),
    untagged: bool = typer.Option(False, "--untagged", "-u", help="Nur ungetaggte Dokumente"),
    all_docs: bool = typer.Option(False, "--all", "-a", help="Bereits verarbeitete einbeziehen"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximale Anzahl"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Statusmeldungen anzeigen"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Debug-Ausgaben anzeigen"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Pfad zur Konfiguration")
):
    """Dokumente analysieren (Batch-Modus)."""
    global verbose_mode, debug_mode
    verbose_mode = verbose
    debug_mode = debug
    setup_logging(debug)
    
    config = get_config(config_path)
    
    # Review-Tracker laden
    tracker = ReviewedTracker()
    
    with DocumentAnalyzer(config) as analyzer:
        log_info(f"Verbinde mit Paperless ({config.paperless.url})...")
        log_success("Verbunden.")
        
        if document_id:
            log_info(f"Lade Dokument #{document_id}...")
            docs = [analyzer.paperless.get_document(document_id)]
            docs = [d for d in docs if d]
        else:
            skip = None if all_docs else tracker.reviewed_ids
            filter_desc = "ungetaggte " if untagged else ""
            log_info(f"Lade {filter_desc}Dokumente (max: {limit})...")
            docs = analyzer.get_documents_for_review(
                limit=limit,
                untagged_only=untagged,
                all_docs=all_docs,
                skip_reviewed=skip
            )
        
        if not docs:
            if not all_docs and len(tracker) > 0:
                console.print("[yellow]Keine neuen Dokumente gefunden. Nutze --all um bereits verarbeitete erneut anzuzeigen.[/yellow]")
            else:
                console.print("[yellow]Keine Dokumente gefunden.[/yellow]")
            return
        
        log_success(f"{len(docs)} Dokumente gefunden.")
        
        results = []
        
        # Progress-Bar für Batch-Operationen
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Analysiere Dokumente...", total=len(docs))
            
            for doc in docs:
                progress.update(task, description=f"[cyan]Analysiere #{doc.id}: {doc.title[:30]}...")
                
                log_debug(f"Analysiere Dokument #{doc.id}")
                result = analyzer.analyze_document(doc.id)
                
                if result:
                    results.append((doc, result))
                    log_debug(f"  → Konfidenz: {result.overall_confidence:.0%}, Tags: {len(result.tag_actions)}")
                
                progress.advance(task)
        
        log_success(f"{len(results)} Dokumente analysiert.\n")
        
        # Ergebnisse anzeigen
        _display_results_table(results)
        
        if auto:
            # Automatisch anwenden
            log_info("Wende hohe-Konfidenz-Vorschläge automatisch an...")
            total_changes = 0
            applied_doc_ids = []
            for doc, result in results:
                if result.overall_confidence >= 0.7:
                    changes = analyzer.apply_result(result)
                    total_changes += len(changes)
                    if changes:
                        applied_doc_ids.append(doc.id)
                    log_debug(f"  #{doc.id}: {len(changes)} Änderungen")
            
            analyzer.save_changes_log()
            if applied_doc_ids:
                tracker.add(applied_doc_ids)
                tracker.save()
            console.print(f"\n[green]✓ {total_changes} Änderungen automatisch angewendet.[/green]")
        else:
            # Nachfragen
            high_conf = [(d, r) for d, r in results if r.overall_confidence >= 0.7]
            if high_conf:
                if Confirm.ask(f"\n[cyan]{len(high_conf)} Vorschläge mit hoher Konfidenz anwenden?[/cyan]"):
                    log_info("Wende Änderungen an...")
                    total_changes = 0
                    applied_doc_ids = []
                    for doc, result in high_conf:
                        changes = analyzer.apply_result(result)
                        total_changes += len(changes)
                        if changes:
                            applied_doc_ids.append(doc.id)
                    
                    analyzer.save_changes_log()
                    if applied_doc_ids:
                        tracker.add(applied_doc_ids)
                        tracker.save()
                    console.print(f"[green]✓ {total_changes} Änderungen angewendet.[/green]")


def _display_results_table(results):
    """Tabelle mit Analyseergebnissen anzeigen."""
    table = Table(title="Analyseergebnisse")
    table.add_column("ID", style="cyan", width=6)
    table.add_column("Titel", style="white", max_width=30)
    table.add_column("+ Tags", style="green")
    table.add_column("- Tags", style="red")
    table.add_column("Korrespondent", style="blue")
    table.add_column("Typ", style="magenta")
    table.add_column("Konf.", justify="right")
    
    for doc, result in results:
        add_tags = [ta.tag for ta in result.tag_actions if ta.action == "add"][:2]
        remove_tags = [ta.tag for ta in result.tag_actions if ta.action == "remove"][:2]
        
        conf_color = "green" if result.overall_confidence >= 0.7 else "yellow" if result.overall_confidence >= 0.5 else "red"
        
        table.add_row(
            str(result.document_id),
            doc.title[:30] + "..." if len(doc.title) > 30 else doc.title,
            ", ".join(add_tags) if add_tags else "-",
            ", ".join(remove_tags) if remove_tags else "-",
            (result.correspondent_suggestion.suggested_value[:20] if result.correspondent_suggestion else "-"),
            (result.document_type_suggestion.suggested_value if result.document_type_suggestion else "-"),
            f"[{conf_color}]{result.overall_confidence:.0%}[/{conf_color}]"
        )
    
    console.print(table)


@app.command()
def validate(
    document_id: Optional[int] = typer.Option(None, "--id", "-i", help="Einzelnes Dokument"),
    tags_only: bool = typer.Option(False, "--tags-only", help="Nur Tags prüfen"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximale Anzahl"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Statusmeldungen anzeigen"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Debug-Ausgaben anzeigen"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Pfad zur Konfiguration")
):
    """Bestehende Metadaten validieren."""
    global verbose_mode, debug_mode
    verbose_mode = verbose
    debug_mode = debug
    setup_logging(debug)
    
    config = get_config(config_path)
    
    with DocumentAnalyzer(config) as analyzer:
        log_info(f"Verbinde mit Paperless ({config.paperless.url})...")
        log_success("Verbunden.")
        
        if document_id:
            log_info(f"Lade Dokument #{document_id}...")
            docs = [analyzer.paperless.get_document(document_id)]
            docs = [d for d in docs if d]
        else:
            # Nur getaggte Dokumente prüfen
            log_info(f"Lade getaggte Dokumente (max: {limit})...")
            all_docs = analyzer.paperless.get_documents(limit=limit * 2)
            docs = [d for d in all_docs if d.tags][:limit]
        
        if not docs:
            console.print("[yellow]Keine Dokumente zum Validieren gefunden.[/yellow]")
            return
        
        log_success(f"{len(docs)} Dokumente zum Validieren gefunden.\n")
        
        issues_found = 0
        
        # Progress-Bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Validiere Dokumente...", total=len(docs))
            
            for doc in docs:
                progress.update(task, description=f"[cyan]Validiere #{doc.id}...")
                
                result = analyzer.analyze_document(doc.id)
                if not result:
                    progress.advance(task)
                    continue
                
                # Prüfe auf Probleme
                has_issues = False
                issues = []
                
                # Prüfe Tag-Entfernungen
                remove_tags = [ta for ta in result.tag_actions if ta.action == "remove"]
                if remove_tags:
                    has_issues = True
                    for ta in remove_tags:
                        issues.append(f"Tag entfernen: {ta.tag} ({ta.confidence:.0%})")
                
                # Prüfe Korrespondent-Änderung
                if result.correspondent_suggestion and not tags_only:
                    has_issues = True
                    cs = result.correspondent_suggestion
                    issues.append(f"Korrespondent: {cs.current_value} → {cs.suggested_value} ({cs.confidence:.0%})")
                
                if has_issues:
                    issues_found += 1
                    log_debug(f"Dokument #{doc.id}: {len(issues)} Probleme gefunden")
                
                progress.advance(task)
        
        # Ergebnisse anzeigen (nach Progress-Bar)
        if issues_found > 0:
            console.print(f"\n[yellow]⚠ {issues_found} Dokumente mit potenziellen Problemen.[/yellow]")
            console.print("[dim]Nutze 'review --id <ID>' um einzelne Dokumente zu prüfen.[/dim]")
        else:
            console.print("\n[green]✓ Keine Probleme gefunden.[/green]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Suchanfrage"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximale Anzahl Ergebnisse"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Statusmeldungen anzeigen"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Debug-Ausgaben anzeigen"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Pfad zur Konfiguration")
):
    """Natürliche Suche in Dokumenten."""
    global verbose_mode, debug_mode
    verbose_mode = verbose
    debug_mode = debug
    setup_logging(debug)
    
    config = get_config(config_path)
    
    with DocumentAnalyzer(config) as analyzer:
        log_info(f"Suche nach: {query}...")
        results = analyzer.search(query, limit)
        
        if results:
            log_success(f"{len(results)} Ergebnisse gefunden.\n")
            _display_search_results(results)
        else:
            console.print("[yellow]Keine Ergebnisse gefunden.[/yellow]")


@app.command()
def history(
    document_id: Optional[int] = typer.Option(None, "--id", "-i", help="Filter nach Dokument-ID"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximale Anzahl"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Statusmeldungen anzeigen"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Debug-Ausgaben anzeigen"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Pfad zur Konfiguration")
):
    """Änderungshistorie anzeigen."""
    global verbose_mode, debug_mode
    verbose_mode = verbose
    debug_mode = debug
    setup_logging(debug)
    
    config = get_config(config_path)
    
    with DocumentAnalyzer(config) as analyzer:
        log_info("Lade Änderungshistorie...")
        analyzer.load_changes_log()
        
        changes = analyzer.changes_log[-limit:]
        if document_id:
            changes = [c for c in changes if c.document_id == document_id]
            log_debug(f"Filter: {len(changes)} Einträge für Dokument #{document_id}")
        
        if changes:
            log_success(f"{len(changes)} Änderungen gefunden.\n")
            _display_history(changes)
        else:
            console.print("[yellow]Keine Änderungen gefunden.[/yellow]")


def _display_search_results(results):
    """Suchergebnisse anzeigen."""
    table = Table(title="Suchergebnisse")
    table.add_column("ID", style="cyan", width=6)
    table.add_column("Titel", style="green")
    table.add_column("Tags", style="blue")
    table.add_column("Auszug", style="dim", max_width=50)
    
    for doc in results:
        table.add_row(
            str(doc.id),
            doc.title,
            ", ".join(doc.tags[:3]) if doc.tags else "-",
            doc.content_preview[:50] + "..." if len(doc.content_preview) > 50 else doc.content_preview
        )
    
    console.print(table)


def _display_history(changes):
    """Änderungshistorie anzeigen."""
    table = Table(title="Änderungshistorie")
    table.add_column("Zeitpunkt", style="cyan")
    table.add_column("Dokument", style="blue", width=8)
    table.add_column("Feld", style="green")
    table.add_column("Aktion", style="yellow")
    table.add_column("Wert", style="magenta")
    table.add_column("Konf.", justify="right")
    
    for change in changes:
        conf_color = "green" if change.confidence >= 0.7 else "yellow" if change.confidence >= 0.5 else "red"
        
        if change.action == "add":
            value = f"+ {change.new_value}"
        elif change.action == "remove":
            value = f"- {change.old_value}"
        else:
            value = change.new_value or "-"
        
        table.add_row(
            change.timestamp.strftime("%Y-%m-%d %H:%M"),
            f"#{change.document_id}",
            change.field,
            change.action,
            value[:30],
            f"[{conf_color}]{change.confidence:.0%}[/{conf_color}]"
        )
    
    console.print(table)


if __name__ == "__main__":
    app()
