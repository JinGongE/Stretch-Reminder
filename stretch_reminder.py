import os
import sys
import time
import json
import logging
import threading
import queue
import subprocess
import winreg
from pathlib import Path
from winotify import Notification, audio
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox

# 프로그램 정보
VERSION = "1.0.0"
APP_NAME = "Stretch Reminder"
AUTHOR = "스트레칭 리마인더"

# 설정 파일 및 전역 변수
CONFIG_FILE = "config.json"
timer = None
interval_sec = None
next_run_time = None
settings_window = None
root = None
tray_icon = None
command_queue = queue.Queue()
running = True
thread_lock = threading.Lock()

def get_app_path():
    """실행 파일의 절대 경로 반환"""
    if getattr(sys, 'frozen', False):
        # PyInstaller로 패키징된 경우
        return Path(sys.executable).parent
    else:
        # 개발 환경
        return Path(__file__).resolve().parent

def get_icon_abs_path():
    """
    1) config.json에서 icon_path를 읽어오고,
    2) 상대경로라면 현재 스크립트 파일 위치를 기준으로 절대경로로 변환한 뒤,
    3) 파일 존재 여부를 검사하여
    4) 최종 절대경로 문자열을 반환합니다.
    
    파일이 없으면 FileNotFoundError를 발생시킵니다.
    """
    try:
        # 1) 설정 로드
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        icon_path = cfg.get("icon_path", "icon.ico")

        # 2) Path 객체 생성 및 절대경로 변환
        p = Path(icon_path)
        if not p.is_absolute():
            # 앱 경로 기준으로 상대경로 해석
            base_dir = get_app_path()
            p = base_dir / icon_path
        p = p.resolve()

        # 3) 파일 존재 여부 확인
        if not p.exists():
            raise FileNotFoundError(f"아이콘 파일을 찾을 수 없습니다: {p}")

        # 4) 절대경로 반환
        return str(p)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        logging.error(f"아이콘 경로 설정 오류: {e}")
        # 기본 아이콘 경로 시도
        default_icon = get_app_path() / "icon.ico"
        if default_icon.exists():
            return str(default_icon)
        else:
            raise FileNotFoundError("기본 아이콘 파일도 찾을 수 없습니다.")

def validate_interval(interval_min):
    """간격 설정값 검증"""
    try:
        interval_min = float(interval_min)
        if interval_min <= 0:
            raise ValueError("간격은 0보다 커야 합니다.")
        if interval_min > 1440:  # 24시간 제한
            raise ValueError("간격은 24시간(1440분)을 초과할 수 없습니다.")
        return max(0.1, interval_min)  # 최소 6초(0.1분) 보장
    except (ValueError, TypeError):
        raise ValueError("유효한 숫자를 입력해주세요.")

def load_config():
    default = {
        "interval_min": 60,
        "icon_path": "icon.ico",
        "log_file": "stretch_reminder.log",
        "auto_start": False,
        "minimize_to_tray": True
    }
    
    config_path = get_app_path() / CONFIG_FILE
    if not config_path.exists():
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=4, ensure_ascii=False)
            print(f"[설정 파일 생성됨] {config_path}")
            print("기본 설정: 60분 간격으로 알림")
            print("프로그램을 시작합니다...")
            # 프로그램 종료하지 않고 기본 설정으로 계속 실행
            return default
        except Exception as e:
            print(f"설정 파일 생성 실패: {e}")
            print("기본 설정으로 실행합니다.")
            return default
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # 설정값 검증 및 기본값 적용
        config["interval_min"] = validate_interval(config.get("interval_min", 60))
        config["icon_path"] = config.get("icon_path", "icon.ico")
        config["log_file"] = config.get("log_file", "stretch_reminder.log")
        config["auto_start"] = config.get("auto_start", False)
        config["minimize_to_tray"] = config.get("minimize_to_tray", True)
        
        return config
    except (json.JSONDecodeError, ValueError) as e:
        print(f"설정 파일 오류: {e}")
        print("기본 설정으로 실행합니다.")
        return default

def setup_logging(log_path):
    try:
        log_file_path = get_app_path() / log_path
        # Python 3.9+ 에서 지원
        logging.basicConfig(
            filename=log_file_path,
            encoding="utf-8",
            level=logging.INFO,
            format="%(asctime)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        logging.info(f"스트레칭 리마인더 v{VERSION} 시작 (간격: %.1f분)", interval_sec / 60)
    except Exception as e:
        print(f"로그 설정 실패: {e}")
        # 기본 로깅 설정
        logging.basicConfig(level=logging.INFO)

def set_auto_start(enable=True):
    """윈도우 시작 시 자동 실행 설정/해제"""
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_path = get_app_path()
        
        if getattr(sys, 'frozen', False):
            # PyInstaller로 패키징된 경우
            exe_path = str(app_path / f"{APP_NAME}.exe")
        else:
            # 개발 환경
            exe_path = str(app_path / "stretch_reminder.py")
        
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if enable:
                # 아이콘 경로도 함께 설정
                icon_path = get_icon_abs_path()
                
                # 실행 경로에 따옴표 추가 (공백이 있을 경우를 대비)
                if " " in exe_path:
                    exe_path = f'"{exe_path}"'
                
                # 아이콘 정보를 포함한 실행 문자열 생성
                # Windows는 실행 파일에서 자동으로 아이콘을 추출하지만,
                # 명시적으로 아이콘 경로를 지정할 수도 있습니다
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
                
                # 추가 정보를 위한 별도 키 생성 (선택사항)
                try:
                    info_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run\StretchReminderInfo"
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, info_key_path) as info_key:
                        winreg.SetValueEx(info_key, "IconPath", 0, winreg.REG_SZ, icon_path)
                        winreg.SetValueEx(info_key, "Version", 0, winreg.REG_SZ, VERSION)
                        winreg.SetValueEx(info_key, "Description", 0, winreg.REG_SZ, "스트레칭 알림 프로그램")
                except Exception as e:
                    logging.warning(f"추가 정보 키 생성 실패: {e}")
                
                logging.info(f"자동 시작 설정 완료: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    
                    # 추가 정보 키도 삭제
                    try:
                        info_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run\StretchReminderInfo"
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, info_key_path)
                    except FileNotFoundError:
                        pass  # 키가 없으면 무시
                    
                    logging.info("자동 시작 해제 완료")
                except FileNotFoundError:
                    logging.info("자동 시작이 이미 해제되어 있음")
        
        return True
    except Exception as e:
        logging.error(f"자동 시작 설정 실패: {e}")
        return False

def get_auto_start_status():
    """자동 시작 상태 확인"""
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logging.error(f"자동 시작 상태 확인 실패: {e}")
        return False

def send_notification(title, message, icon_path):
    try:
        # winotify로 알림 생성
        toast = Notification(
            app_id=APP_NAME,  # 알림 헤더에 표시될 이름
            title=title,
            msg=message,
            icon=icon_path
        )
        # 기본 알림음 설정
        toast.set_audio(audio.Default, loop=False)
        # 알림 표시
        toast.show()
        # 로그 기록
        logging.info(f"알림 전송: {title} - {message}")
    except Exception as e:
        logging.error(f"알림 전송 실패: {e}")
        print(f"알림 전송 실패: {e}")

def schedule_notification(title, message, icon_path):
    global timer, next_run_time
    try:
        # 스레드 락을 최소한으로 사용
        current_interval = interval_sec
        next_run_time = time.time() + current_interval
        
        # 타이머 생성 및 시작
        timer = threading.Timer(current_interval,
                                 notify_and_reschedule,
                                 args=(title, message, icon_path))
        timer.daemon = True
        timer.start()
        logging.info(f"다음 알림 예약: {current_interval}초 후")
    except Exception as e:
        logging.error(f"알림 예약 실패: {e}")

def notify_and_reschedule(title, message, icon_path):
    try:
        send_notification(title, message, icon_path)
        if running:  # 프로그램이 실행 중일 때만 재예약
            # 약간의 지연 후 재예약 (안정성을 위해)
            def delayed_reschedule():
                try:
                    time.sleep(0.1)  # 0.1초 지연
                    if running:  # 다시 확인
                        schedule_notification(title, message, icon_path)
                except Exception as e:
                    logging.error(f"지연된 재예약 실패: {e}")
            
            # 별도 스레드에서 지연된 재예약
            reschedule_thread = threading.Thread(target=delayed_reschedule, daemon=True)
            reschedule_thread.start()
    except Exception as e:
        logging.error(f"알림 및 재예약 실패: {e}")

def on_exit(icon, _item):
    """우클릭 메뉴에서 '종료'를 선택했을 때 호출"""
    try:
        command_queue.put("exit")
    except Exception as e:
        print(f"종료 명령 전송 실패: {e}")
        sys.exit(1)

def on_open_settings(icon, _item):
    """설정 열기 명령 전송"""
    try:
        command_queue.put("open_settings")
    except Exception as e:
        print(f"설정 열기 명령 전송 실패: {e}")

# ─── "설정 열기" GUI ──────────────────────────────────────────────────────────
def create_settings_window():
    global settings_window, root
    
    # 이미 설정 창이 열려있으면 포커스만 이동
    if settings_window and settings_window.winfo_exists():
        try:
            settings_window.lift()  # 창을 앞으로 가져오기
            settings_window.focus_force()  # 포커스 강제 설정
            return
        except Exception as e:
            logging.error(f"기존 창 포커스 실패: {e}")
            settings_window = None
    
    try:
        window = tk.Toplevel(root)  # root를 부모로 사용
        settings_window = window
        
        # 창 아이콘 설정 (더 안전한 방법)
        try:
            icon_path = get_icon_abs_path()
            # .ico 파일인지 확인
            if icon_path.lower().endswith('.ico'):
                window.iconbitmap(icon_path)
            else:
                # .ico가 아니면 PIL을 사용해 변환 시도
                img = Image.open(icon_path)
                # 작은 크기로 리사이즈 (아이콘용)
                img = img.resize((32, 32), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                window.iconphoto(True, photo)
            logging.info(f"설정 창 아이콘 설정 완료: {icon_path}")
        except FileNotFoundError as e:
            logging.warning(f"아이콘 파일을 찾을 수 없음: {e}")
        except Exception as e:
            logging.error(f"아이콘 로드 실패: {e}")
            # 아이콘 설정 실패해도 창은 정상 작동
        
        # ─── 칼럼을 동일 비율로 확장해 가운데 정렬될 수 있는 공간 확보 ───
        window.columnconfigure(0, weight=1)
        window.columnconfigure(1, weight=1)
        #기본 윈도우 크기 지정 (너비 x 높이)
        window.geometry("400x350")
        window.title(f"{APP_NAME} 설정")
        window.resizable(False, False)  # 크기 고정
        
        # 창을 화면 중앙에 위치
        window.update_idletasks()
        x = (window.winfo_screenwidth() // 2) - (400 // 2)
        y = (window.winfo_screenheight() // 2) - (350 // 2)
        window.geometry(f"400x350+{x}+{y}")

        # 제목
        title_label = tk.Label(window, text=f"{APP_NAME} 설정", font=("Arial", 14, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(20, 10))

        # 알림 간격 설정
        tk.Label(window,
                 text="알림 간격 (분):",
                 anchor='center',     
                 justify='center').grid(row=1, column=0, padx=5, pady=(10,5))

        interval_var = tk.StringVar(value=f"{interval_sec / 60:.1f}")
        interval_entry = tk.Entry(window, textvariable=interval_var, width=10)
        interval_entry.grid(row=1, column=1, padx=5, pady=(10, 5))

        # 도움말 텍스트
        help_text = tk.Label(window, 
                           text="(0.1~1440분, 소수점 가능)",
                           font=("Arial", 8),
                           fg="gray")
        help_text.grid(row=2, column=0, columnspan=2, pady=(0, 10))

        # 자동 시작 설정
        auto_start_var = tk.BooleanVar(value=get_auto_start_status())
        auto_start_check = tk.Checkbutton(window, 
                                         text="윈도우 시작 시 자동 실행",
                                         variable=auto_start_var)
        auto_start_check.grid(row=3, column=0, columnspan=2, pady=(10, 5))

        def apply_settings():
            nonlocal interval_var, auto_start_var
            try:
                new_min = validate_interval(interval_var.get())
                
                # config.json 갱신
                cfg = load_config()
                cfg["interval_min"] = new_min
                cfg["auto_start"] = auto_start_var.get()
                with open(get_app_path() / CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4, ensure_ascii=False)
                
                # 자동 시작 설정/해제
                set_auto_start(auto_start_var.get())
                
                # 타이머 재설정 (락 사용하지 않고 직접 처리)
                global interval_sec, timer
                
                # 기존 타이머 취소
                if timer:
                    timer.cancel()
                
                # 새로운 간격 설정
                interval_sec = new_min * 60
                
                # 새로운 타이머 시작 (별도 스레드에서)
                def start_new_timer():
                    try:
                        schedule_notification(title, message, icon_path)
                    except Exception as e:
                        logging.error(f"새 타이머 시작 실패: {e}")
                
                # 별도 스레드에서 타이머 시작
                timer_thread = threading.Thread(target=start_new_timer, daemon=True)
                timer_thread.start()
                
                messagebox.showinfo("성공", f"설정이 적용되었습니다.\n새로운 간격: {new_min:.1f}분")
                logging.info(f"설정 변경: {new_min:.1f}분 간격, 자동시작: {auto_start_var.get()}")
                
            except ValueError as e:
                messagebox.showerror("오류", str(e))
                interval_var.set(f"{interval_sec / 60:.1f}")  # 원래 값으로 복원
            except Exception as e:
                messagebox.showerror("오류", f"설정 적용 실패: {e}")
                logging.error(f"설정 적용 실패: {e}")

        apply_button = tk.Button(window, text="적용", command=apply_settings)
        apply_button.grid(row=4, column=0, columnspan=2, pady=(10,20))

        # 2) 남은 시간 실시간 표시
        next_run_label = tk.Label(window,
                                text="",
                                anchor='center',   # 텍스트 중심 정렬
                                justify='center')
        next_run_label.grid(row=5, column=0, columnspan=2, pady=5)

        def update_countdown():
            try:
                if next_run_time:
                    remaining = int(next_run_time - time.time())
                    if remaining < 0: 
                        remaining = 0
                    m, s = divmod(remaining, 60)
                    next_run_label.config(text=f"다음 알림까지: {m}분 {s}초")
                window.after(1000, update_countdown)
            except Exception as e:
                logging.error(f"카운트다운 업데이트 실패: {e}")
                window.after(1000, update_countdown)
        
        update_countdown()

        # 창 닫기 시 처리
        def on_closing():
            global settings_window
            try:
                settings_window = None
                window.destroy()
            except Exception as e:
                logging.error(f"창 닫기 실패: {e}")
        
        window.protocol("WM_DELETE_WINDOW", on_closing)
        
    except Exception as e:
        logging.error(f"설정 창 생성 실패: {e}")
        print(f"설정 창 생성 실패: {e}")
        settings_window = None

def process_commands():
    """명령 큐에서 명령을 처리하는 함수"""
    global running
    try:
        while running:
            try:
                command = command_queue.get(timeout=0.1)  # 0.1초 타임아웃
                if command == "exit":
                    running = False
                    cleanup_and_exit()
                    break
                elif command == "open_settings":
                    create_settings_window()
                elif command == "toggle_auto_start":
                    current_status = get_auto_start_status()
                    new_status = not current_status
                    if set_auto_start(new_status):
                        status_text = "설정" if new_status else "해제"
                        messagebox.showinfo("자동 시작", f"자동 시작이 {status_text}되었습니다.")
                    else:
                        messagebox.showerror("오류", "자동 시작 설정에 실패했습니다.")
            except queue.Empty:
                pass
            
            # Tkinter 이벤트 처리
            if root and running:
                try:
                    root.update()
                except Exception as e:
                    logging.error(f"Tkinter 업데이트 실패: {e}")
                    break
                    
    except Exception as e:
        logging.error(f"명령 처리 실패: {e}")
        cleanup_and_exit()

def cleanup_and_exit():
    """프로그램 정리 및 종료"""
    global running
    running = False
    
    try:
        global timer, tray_icon, settings_window, root
        
        # 타이머 정리 (락 없이 직접 처리)
        if timer:
            try:
                timer.cancel()
                timer = None
            except Exception as e:
                logging.error(f"타이머 취소 실패: {e}")
        
        # Tkinter 창들 정리
        if settings_window and settings_window.winfo_exists():
            try:
                settings_window.destroy()
                settings_window = None
            except Exception as e:
                logging.error(f"설정 창 정리 실패: {e}")
        
        # 트레이 아이콘 정리
        if tray_icon:
            try:
                tray_icon.stop()
                tray_icon = None
            except Exception as e:
                logging.error(f"트레이 아이콘 정리 실패: {e}")
        
        # 루트 창 정리
        if root:
            try:
                root.quit()
                root.destroy()
                root = None
            except Exception as e:
                logging.error(f"루트 창 정리 실패: {e}")
        
        logging.info("프로그램 종료")
        sys.exit(0)
        
    except Exception as e:
        print(f"종료 중 오류: {e}")
        logging.error(f"종료 중 오류: {e}")
        sys.exit(1)

def main():
    global interval_sec, title, message, icon_path, log_file, root, tray_icon

    try:
        # 1) 설정 로드
        cfg = load_config()
        interval_sec = cfg["interval_min"] * 60
        icon_path = get_icon_abs_path()
        log_file = cfg["log_file"]

        # 2) 로깅 설정
        setup_logging(log_file)

        # 3) 토스터 준비
        title = "스트레칭 알림"
        message = "스트레칭 시간입니다!"

        # 4) 첫 알림 예약
        schedule_notification(title, message, icon_path)

        # 5) Tkinter 루트 창 생성 (숨김)
        root = tk.Tk()
        root.withdraw()  # 루트 창 숨기기
        
        # 6) 시스템 트레이 아이콘 세팅 (별도 스레드)
        def create_tray_icon():
            global tray_icon
            try:
                image = Image.open(icon_path)
                menu = (
                    item('설정 열기', on_open_settings),
                    item('종료', on_exit),
                )
                tray_icon = pystray.Icon("StretchReminder", image, f"{APP_NAME} v{VERSION}", menu)
                tray_icon.run()
            except Exception as e:
                logging.error(f"트레이 아이콘 생성 실패: {e}")
                command_queue.put("exit")
        
        # 트레이 아이콘을 별도 스레드에서 실행
        tray_thread = threading.Thread(target=create_tray_icon, daemon=True)
        tray_thread.start()
        
        # 시작 알림 (config 파일이 새로 생성된 경우 더 친화적인 메시지)
        config_path = get_app_path() / CONFIG_FILE
        if config_path.exists() and config_path.stat().st_mtime > time.time() - 10:  # 10초 이내에 생성된 파일
            send_notification("환영합니다!", f"{APP_NAME} v{VERSION}이 시작되었습니다.\n기본 설정: {interval_sec/60:.0f}분 간격", icon_path)
        else:
            send_notification("", f"{APP_NAME} v{VERSION}을 실행합니다.", icon_path)
        
        # 7) 메인 이벤트 루프 (명령 처리)
        process_commands()
        
    except Exception as e:
        print(f"프로그램 시작 실패: {e}")
        logging.error(f"프로그램 시작 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
