#!/usr/bin/env python3
"""
스트레칭 리마인더 실행 파일 빌드 스크립트
PyInstaller를 사용하여 Windows 실행 파일을 생성합니다.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def build_executable():
    """PyInstaller를 사용하여 실행 파일 빌드"""
    
    # 현재 디렉토리
    current_dir = Path(__file__).parent
    
    # PyInstaller 명령어 구성
    cmd = [
        "pyinstaller",
        "--onefile",                    # 단일 실행 파일
        "--windowed",                   # 콘솔 창 숨김
        "--name=Stretch Reminder",      # 실행 파일 이름
        "--icon=icon.ico",              # 아이콘 설정
        "--add-data=icon.ico;.",        # 아이콘 파일 포함
        "--hidden-import=PIL._tkinter_finder",  # PIL 의존성
        "--hidden-import=winotify",     # winotify 의존성
        "--hidden-import=pystray",      # pystray 의존성
        "--hidden-import=winreg",       # winreg 의존성
        "--version-file=version_info.txt",  # 버전 정보 파일
        "--clean",                      # 빌드 전 정리
        "stretch_reminder.py"           # 메인 스크립트
    ]
    
    print("🚀 실행 파일 빌드를 시작합니다...")
    print(f"명령어: {' '.join(cmd)}")
    
    try:
        # PyInstaller 실행
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ 빌드가 성공적으로 완료되었습니다!")
        
        # 실행 파일 경로
        exe_path = current_dir / "dist" / "Stretch Reminder.exe"
        
        if exe_path.exists():
            print(f"📁 실행 파일 위치: {exe_path}")
            print(f"📊 파일 크기: {exe_path.stat().st_size / (1024*1024):.1f} MB")
            
            # 배포 폴더 생성
            dist_folder = current_dir / "release"
            dist_folder.mkdir(exist_ok=True)
            
            # 실행 파일 복사
            shutil.copy2(exe_path, dist_folder / "Stretch Reminder.exe")
            
            # 아이콘 파일 복사
            if (current_dir / "icon.ico").exists():
                shutil.copy2(current_dir / "icon.ico", dist_folder / "icon.ico")
            
            # README 복사
            if (current_dir / "README.md").exists():
                shutil.copy2(current_dir / "README.md", dist_folder / "README.md")
            
            print(f"📦 배포 폴더가 생성되었습니다: {dist_folder}")
            print("\n🎉 배포 준비가 완료되었습니다!")
            
        else:
            print("❌ 실행 파일을 찾을 수 없습니다.")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"❌ 빌드 실패: {e}")
        print(f"오류 출력: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        return False
    
    return True

def clean_build_files():
    """빌드 임시 파일 정리"""
    current_dir = Path(__file__).parent
    
    # 정리할 폴더들
    folders_to_clean = ["build", "dist", "__pycache__"]
    
    for folder in folders_to_clean:
        folder_path = current_dir / folder
        if folder_path.exists():
            try:
                shutil.rmtree(folder_path)
                print(f"🧹 {folder} 폴더를 정리했습니다.")
            except Exception as e:
                print(f"⚠️ {folder} 폴더 정리 실패: {e}")

def check_dependencies():
    """필요한 의존성 확인"""
    required_packages = [
        ("pyinstaller", "PyInstaller"),
        ("winotify", "winotify"), 
        ("pystray", "pystray"),
        ("Pillow", "PIL")
    ]
    missing_packages = []
    
    for package_name, import_name in required_packages:
        try:
            __import__(import_name)
            print(f"✅ {package_name} 설치됨")
        except ImportError:
            missing_packages.append(package_name)
            print(f"❌ {package_name} 누락됨")
    
    if missing_packages:
        print(f"\n❌ 누락된 패키지: {', '.join(missing_packages)}")
        print("다음 명령어로 설치하세요:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    print("\n✅ 모든 의존성이 설치되어 있습니다.")
    return True

if __name__ == "__main__":
    print("=" * 50)
    print("스트레칭 리마인더 빌드 도구")
    print("=" * 50)
    
    # 의존성 확인
    if not check_dependencies():
        sys.exit(1)
    
    # 사용자 선택
    print("\n옵션을 선택하세요:")
    print("1. 빌드 실행")
    print("2. 빌드 파일 정리")
    print("3. 빌드 + 정리")
    
    try:
        choice = input("\n선택 (1-3): ").strip()
        
        if choice == "1":
            build_executable()
        elif choice == "2":
            clean_build_files()
        elif choice == "3":
            build_executable()
            if input("\n빌드 파일을 정리하시겠습니까? (y/n): ").lower() == 'y':
                clean_build_files()
        else:
            print("❌ 잘못된 선택입니다.")
            
    except KeyboardInterrupt:
        print("\n\n❌ 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}") 