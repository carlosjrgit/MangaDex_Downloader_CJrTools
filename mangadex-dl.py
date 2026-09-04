#!/usr/bin/env python3
"""
mangadex-dl.py - Downloader em Linha de Comando (CLI) para MangaDex e MangaLivre
Suporte a múltiplos links em lote (Fila de Tarefas), estimativas de tamanho/tempo,
seleção flexível de capítulos, controle de pausa/interrupção e retomada automática.
"""

import argparse
import logging
import os
import signal
import sys
import time
from typing import List

from tqdm import tqdm

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from manga_core import (
    ChapterMode,
    DownloadEngine,
    ExecutionController,
    ProviderRegistry,
    QueueTask,
    StateManager,
    TaskStatus,
    calculate_task_estimates,
    clean_filename,
    create_session,
    format_size,
    format_time,
    parse_chapter_selection,
    safe_path_join
)

__version__ = "1.1.0"

# ----------------------------------------------------------------------
# Configuração de Logs
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("mangadex-dl")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)


# ----------------------------------------------------------------------
# Funções de Análise e Preparação da Fila no CLI
# ----------------------------------------------------------------------
def analyze_task_cli(task: QueueTask, session) -> bool:
    """Extrai metadados e capítulos da obra para exibição no terminal."""
    try:
        provider = ProviderRegistry.get_provider_for_url(task.url, session=session)
        task.provider = provider.name
        print(f"  [+] Fonte detectada: {provider.display_name}")
        info = provider.get_manga_info(task.url, session, task.lang_code)
        task.title = info["title"]
        task.cover_url = info.get("cover_url", "")
        task.available_langs = info.get("available_langs", ["pt-br"])
        task.all_chapters = info["chapters"]

        task.selected_chapters = parse_chapter_selection(
            task.all_chapters, task.chapter_mode, task.chapter_mode_value
        )
        task.estimated_size_mb, task.estimated_seconds = calculate_task_estimates(task)
        task.status = TaskStatus.READY
        return True
    except Exception as e:
        task.status = TaskStatus.ERROR
        task.error_message = str(e)
        logger.error("Erro ao analisar '%s': %s", task.url, e)
        return False


def print_queue_summary(tasks: List[QueueTask]):
    """Exibe tabela formatada da fila no terminal."""
    print("\n" + "=" * 80)
    print(f"{'#':<3} {'OBRA / TÍTULO':<32} {'FONTE':<11} {'CAPS':<8} {'TAM. EST.':<12} {'TEMPO EST.':<10}")
    print("-" * 80)
    total_mb = 0.0
    total_sec = 0.0
    for idx, t in enumerate(tasks, 1):
        prov = ProviderRegistry.get_provider(t.provider).display_name
        caps_str = f"{len(t.selected_chapters)} caps"
        size_str = f"~{format_size(t.estimated_size_mb)}"
        time_str = f"~{format_time(t.estimated_seconds)}"
        title_trunc = t.title[:30] + ".." if len(t.title) > 30 else t.title
        print(f"{idx:<3} {title_trunc:<32} {prov:<11} {caps_str:<8} {size_str:<12} {time_str:<10}")
        total_mb += t.estimated_size_mb
        total_sec += t.estimated_seconds
    print("=" * 80)
    print(f"Total na Fila: {len(tasks)} obra(s) | Tamanho Total Est: ~{format_size(total_mb)} | Tempo Total Est: ~{format_time(total_sec)}")
    print("=" * 80 + "\n")


# ----------------------------------------------------------------------
# Loop Principal de Download no CLI
# ----------------------------------------------------------------------
def run_cli_queue(tasks: List[QueueTask], args: argparse.Namespace):
    controller = ExecutionController()
    engine = DownloadEngine(controller=controller)

    # Manipulador de sinal de interrupção (Ctrl+C)
    def sigint_handler(signum, frame):
        print("\n\n⚠️ Interrupção detectada (Ctrl+C)!")
        print("  [P]ausar / [C]ontinuar / [S]air e salvar progresso")
        try:
            choice = input("Escolha uma opção (P/C/S) [Padrão: S]: ").strip().lower()
            if choice == "p":
                controller.pause()
                print("⏸ Fila pausada. Pressione Enter para continuar...")
                input()
                controller.resume()
                print("▶ Fila retomada.")
            elif choice == "c":
                print("▶ Continuando execução...")
            else:
                controller.stop()
                print("⏹ Salvando estado da fila e saindo...")
                StateManager.save_queue(tasks)
                sys.exit(0)
        except Exception:
            controller.stop()
            StateManager.save_queue(tasks)
            sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)

    total_tasks = len(tasks)
    print(f"🚀 Iniciando processamento da fila com {total_tasks} obra(s)...\n")

    for t_idx, task in enumerate(tasks, 1):
        if controller.is_stopped():
            break

        if task.status == TaskStatus.COMPLETED:
            print(f"[{t_idx}/{total_tasks}] ✓ {task.title} já baixado anteriormente. Pulando.")
            continue

        print(f"\n[{t_idx}/{total_tasks}] 📁 Processando: {task.title}")
        try:
            dest_display = safe_path_join(task.outdir, clean_filename(task.title))
        except ValueError:
            dest_display = os.path.join(task.outdir, clean_filename(task.title))
        print(f"    Pasta de destino: {dest_display}")
        print(f"    Capítulos a baixar: {len(task.selected_chapters)}")

        chaps_to_download = [
            c for c in task.selected_chapters
            if c.get("id") not in task.downloaded_chapter_ids
        ]

        total_chaps = len(task.selected_chapters)
        already_done = total_chaps - len(chaps_to_download)

        task.status = TaskStatus.DOWNLOADING
        StateManager.save_queue(tasks)

        for c_idx, ch in enumerate(chaps_to_download, start=already_done + 1):
            if controller.check_pause_and_stop():
                break

            chap_num = ch.get("chapter") or ch.get("attributes", {}).get("chapter") or "Oneshot"
            pbar = tqdm(total=100, desc=f"  Cap. {chap_num} [{c_idx}/{total_chaps}]", unit="%", leave=False)

            def page_cb(curr: int, total: int):
                pct = int((curr / total) * 100) if total > 0 else 0
                pbar.n = pct
                pbar.refresh()

            ok, bytes_count = engine.download_chapter(
                task=task,
                chapter=ch,
                workers=args.jobs,
                progress_cb=page_cb
            )

            pbar.close()

            if ok:
                task.downloaded_chapter_ids.append(ch.get("id"))
                task.real_size_bytes += bytes_count
                print(f"  ✓ Capítulo {chap_num} concluído.")
            else:
                if not controller.is_stopped():
                    print(f"  ⚠️ Falha no capítulo {chap_num}.")

            StateManager.save_queue(tasks)

        if not controller.is_stopped():
            task.status = TaskStatus.COMPLETED
            StateManager.save_queue(tasks)
            print(f"✨ Concluído: {task.title} (Tamanho salvo: {format_size(task.real_size_bytes, is_bytes=True)})\n")

    print("\n" + "=" * 80)
    print("🎉 Todos os downloads da fila foram processados!")
    print("=" * 80)


# ----------------------------------------------------------------------
# Entrada Principal (CLI)
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="MangaDex & MangaLivre Downloader - Gerenciador de Fila e Downloads em Lote"
    )
    parser.add_argument("urls", nargs="*", help="Uma ou mais URLs/IDs de mangás (MangaDex ou MangaLivre)")
    parser.add_argument("-f", "--file", help="Arquivo .txt contendo uma lista de URLs (uma por linha)")
    parser.add_argument("-l", "--lang", default="pt-br", help="Idioma preferido (ex: pt-br, en)")
    parser.add_argument("-o", "--outdir", default="download", help="Diretório principal de saída")
    parser.add_argument("-d", "--datasaver", action="store_true", help="Qualidade reduzida / DataSaver (MangaDex)")
    parser.add_argument("--no-cbz", action="store_false", dest="cbz", default=True, help="Não empacotar em .CBZ")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="Número de downloads paralelos de páginas (padrão: 4)")
    parser.add_argument("--resume", action="store_true", help="Retomar fila de downloads pendentes anterior")

    # Modos de Seleção de Capítulos
    group_mode = parser.add_mutually_exclusive_group()
    group_mode.add_argument("--all", action="store_true", help="Baixar todos os capítulos (Padrão)")
    group_mode.add_argument("--latest", action="store_true", help="Baixar apenas o capítulo mais recente")
    group_mode.add_argument("--single", help="Baixar um único capítulo específico (ex: --single 45)")
    group_mode.add_argument("--range", help="Baixar intervalo de capítulos X a Y (ex: --range 1-10 ou 1~10)")
    group_mode.add_argument("--chunk", help="Baixar primeiros N capítulos ou bloco (ex: --chunk 10)")
    group_mode.add_argument("--custom", help="Seleção personalizada (ex: --custom '1, 3, 5-10')")

    args = parser.parse_args()

    print("\n=======================================================")
    print(f" MangaDex & MangaLivre Downloader CLI v{__version__}")
    print("=======================================================\n")

    urls_to_process = []

    # 1. Carregar URLs dos argumentos posicionais
    if args.urls:
        urls_to_process.extend(args.urls)

    # 2. Carregar URLs de arquivo de texto (-f / --file)
    if args.file and os.path.exists(args.file):
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                file_urls = [line.strip() for line in f if line.strip()]
            urls_to_process.extend(file_urls)
            print(f"📄 {len(file_urls)} URL(s) carregada(s) de '{args.file}'.")
        except Exception as e:
            logger.error("Erro ao ler arquivo '%s': %s", args.file, e)

    # 3. Retomar sessão anterior se solicitado
    if args.resume:
        saved_tasks = StateManager.load_queue()
        if saved_tasks:
            pending = [t for t in saved_tasks if t.status != TaskStatus.COMPLETED]
            if pending:
                print(f"🔄 Retomando sessão anterior com {len(pending)} obra(s) pendente(s)...")
                print_queue_summary(pending)
                run_cli_queue(pending, args)
                return
            else:
                print("ℹ️ Todas as tarefas da sessão anterior já estão concluídas.")

    # 4. Se nenhuma URL foi passada, solicita interativamente
    if not urls_to_process:
        print("Digite ou cole as URLs dos mangás (uma por linha ou separadas por espaço/vírgula).")
        print("Pressione Enter duas vezes quando terminar:")
        lines = []
        while True:
            try:
                line = input().strip()
                if not line:
                    break
                # Se colou múltiplas separadas por vírgula ou espaço
                for part in line.split(","):
                    for item in part.split():
                        if item.strip():
                            lines.append(item.strip())
            except (KeyboardInterrupt, EOFError):
                break
        urls_to_process.extend(lines)

    if not urls_to_process:
        print("Nenhuma URL fornecida. Saindo.")
        sys.exit(0)

    # Determinar Modo de Capítulos
    if args.latest:
        mode = ChapterMode.LATEST
        mode_val = ""
    elif args.single:
        mode = ChapterMode.SINGLE
        mode_val = args.single
    elif args.range:
        mode = ChapterMode.RANGE
        mode_val = args.range
    elif args.chunk:
        mode = ChapterMode.CHUNK
        mode_val = args.chunk
    elif args.custom:
        mode = ChapterMode.CUSTOM
        mode_val = args.custom
    else:
        mode = ChapterMode.ALL
        mode_val = ""

    # Criar lista de QueueTask
    session = create_session()
    tasks: List[QueueTask] = []
    print("\n🔍 Analisando obras na fila...")

    for idx, u in enumerate(urls_to_process, 1):
        prov_obj = ProviderRegistry.get_provider_for_url(u, session=session)
        prov = prov_obj.name
        task = QueueTask(
            id=f"{time.time()}_{idx}",
            url=u,
            provider=prov,
            lang_code=args.lang,
            chapter_mode=mode,
            chapter_mode_value=mode_val,
            outdir=args.outdir,
            cbz=args.cbz,
            datasaver=args.datasaver,
            status=TaskStatus.PENDING
        )
        print(f"  [{idx}/{len(urls_to_process)}] Analisando: {u}...")
        ok = analyze_task_cli(task, session)
        if ok:
            tasks.append(task)

    if not tasks:
        print("❌ Nenhuma obra válida encontrada para baixar.")
        sys.exit(1)

    StateManager.save_queue(tasks)
    print_queue_summary(tasks)

    confirm = input("Deseja iniciar o download da fila agora? [S/n]: ").strip().lower()
    if confirm in ["", "s", "sim", "y", "yes"]:
        run_cli_queue(tasks, args)
    else:
        print("Operação cancelada. A fila foi salva em 'queue_state.json' e pode ser retomada com --resume.")


if __name__ == "__main__":
    main()
