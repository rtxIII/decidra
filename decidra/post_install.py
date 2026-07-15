#!/usr/bin/env python3
"""
Decidra 安装后配置脚本

用途:
- pip install decidra 后自动创建配置目录和文件
- 从安装包复制配置模板到用户目录
- 验证配置完整性

使用方式:
  decidra-init
  或
  python -m decidra.post_install
"""

import sys
import shutil
from pathlib import Path


def print_info(msg):
    """打印信息"""
    print(f"[INFO] {msg}")


def print_success(msg):
    """打印成功信息"""
    print(f"[✓] {msg}")


def print_error(msg):
    """打印错误信息"""
    print(f"[✗] {msg}", file=sys.stderr)


def print_warning(msg):
    """打印警告信息"""
    print(f"[⚠] {msg}")


def verify_installation():
    """验证 Decidra 包是否安装"""
    try:
        import decidra
        version = getattr(decidra, '__version__', 'unknown')
        print_success(f"Decidra v{version} 包已安装")
        return True
    except ImportError as e:
        print_error(f"Decidra 包未正确安装: {e}")
        return False


def initialize_directories():
    """初始化目录结构（使用内置工具）"""
    try:
        # 导入目录初始化工具(同包内导入)
        from .utils.init_dirs import initialize_decidra_dirs

        # 初始化目录
        success = initialize_decidra_dirs(verbose=True)

        if success:
            print_success("目录结构初始化完成")
        else:
            print_warning("部分目录创建失败，但不影响继续")

        return True

    except ImportError as e:
        print_warning(f"无法导入目录初始化工具: {e}")
        # 降级为手动创建
        return create_directories_manually()
    except Exception as e:
        print_error(f"目录初始化失败: {e}")
        return False


def create_directories_manually():
    """手动创建目录（降级方案）"""
    home = Path.home()
    decidra_dir = home / '.decidra'

    print_info("使用手动方式创建目录...")

    # 创建目录列表
    directories = [
        decidra_dir,
        decidra_dir / '.runtime',
        decidra_dir / '.runtime' / 'config',
        decidra_dir / '.runtime' / 'data',
        decidra_dir / '.runtime' / 'log',
    ]

    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            print_success(f"创建目录: {directory}")
        except Exception as e:
            print_error(f"创建目录失败 {directory}: {e}")
            return False

    return True


def copy_config_template():
    """复制配置模板文件"""
    try:
        # 确定目标目录
        home = Path.home()
        decidra_dir = home / '.decidra'

        # 尝试找到配置模板
        import decidra
        pkg_root = Path(decidra.__file__).parent.parent

        # 可能的模板位置
        template_locations = [
            pkg_root / 'config' / 'config_template.ini',
            pkg_root / 'decidra' / 'config' / 'config_template.ini',
            Path(__file__).parent.parent / 'config' / 'config_template.ini'
        ]

        template_source = None
        for location in template_locations:
            if location.exists():
                template_source = location
                break

        if template_source is None:
            print_warning("未找到配置模板，将创建默认配置")
            return create_default_config()

        # 复制模板到用户目录
        template_dest = decidra_dir / 'config_template.ini'
        if not template_dest.exists():
            shutil.copy(template_source, template_dest)
            print_success(f"复制配置模板: {template_dest}")

        # 如果用户配置不存在，复制模板为配置文件
        config_dest = decidra_dir / 'config.ini'
        if not config_dest.exists():
            shutil.copy(template_source, config_dest)
            print_success(f"创建用户配置: {config_dest}")
            print_warning("请编辑 ~/.decidra/config.ini 填写您的配置信息")
        else:
            print_info(f"配置文件已存在，跳过: {config_dest}")

        return True

    except ImportError:
        print_error("无法导入 decidra 包")
        return create_default_config()
    except Exception as e:
        print_error(f"复制配置模板失败: {e}")
        return create_default_config()


def create_default_config():
    """创建默认配置文件（降级方案）"""
    config_content = """[Application]
LogLevel = INFO
LogToFile = true
LogToConsole = false
LogFileMaxSize = 1024
LogFileBackupCount = 2
DebugMode = false
PerformanceMonitoring = false
DataCacheTTL = 300
MaxConcurrentRequests = 10

[FutuOpenD.Config]
Host = 127.0.0.1
Port = 11111
WebSocketPort = 33333
TrdEnv = SIMULATE
Timeout = 10
EnableProtoEncrypt = false
LogLevel = INFO

[FutuOpenD.Credential]
Username =
Password_md5 =

[FutuOpenD.DataFormat]
HistoryDataFormat = ["code","time_key","open","close","high","low","volume","turnover"]
SubscribedDataFormat = None

[TradePreference]
LotSizeMultiplier = 1
MaxPercPerAsset = 10
StockList = []
OrderSize = 100
OrderType = NORMAL
AutoNormalize = true
MaxPositions = 10

[Email]
SmtpServer =
Port = 587
EmailUser =
EmailPass =
EmailTo =
SubscriptionList = []

[TuShare.Credential]
token =

[monitored_stocks]
stock_0 = HK.00700
stock_1 = HK.09988
"""

    home = Path.home()
    decidra_dir = home / '.decidra'
    config_file = decidra_dir / 'config.ini'
    template_file = decidra_dir / 'config_template.ini'

    try:
        # 确保目录存在
        decidra_dir.mkdir(parents=True, exist_ok=True)

        # 创建模板文件
        template_file.write_text(config_content)
        print_success(f"创建配置模板: {template_file}")

        # 如果配置文件不存在，创建它
        if not config_file.exists():
            config_file.write_text(config_content)
            print_success(f"创建用户配置: {config_file}")
            print_warning("请编辑 ~/.decidra/config.ini 填写您的配置信息")
        else:
            print_info(f"配置文件已存在，跳过: {config_file}")

        return True

    except Exception as e:
        print_error(f"创建默认配置失败: {e}")
        return False


def create_readme():
    """创建 README 文件"""
    readme_content = """# Decidra 用户配置目录

此目录包含 Decidra 的所有用户配置和运行时数据。

## 目录结构

```
~/.decidra/
├── config.ini                 # 主配置文件（请编辑此文件）
├── config_template.ini        # 配置模板（参考用）
├── strategy/                  # 策略配置（config.json）
└── .runtime/                  # 运行时数据
    ├── config/                # 运行时配置
    ├── data/                  # 数据缓存
    └── log/                   # 日志文件
```

## 首次配置

1. 编辑配置文件:
   ```bash
   nano ~/.decidra/config.ini
   ```

2. 填写富途 API 连接信息:
   - Host: FutuOpenD 运行地址
   - Port: FutuOpenD 端口
   - Username: 富途账户用户名
   - Password_md5: 交易密码的 MD5 值

3. 验证配置:
   ```bash
   decidra config validate
   decidra futu test-connection
   ```

## 环境变量

支持使用环境变量覆盖配置：

```bash
export FUTU_HOST=127.0.0.1
export FUTU_PORT=11111
export FUTU_TRD_ENV=SIMULATE
export TUSHARE_TOKEN=your_token
```

## 更多帮助

- 文档: https://decidra.readthedocs.io/
- GitHub: https://github.com/rtxIII/decidra
- 问题反馈: https://github.com/rtxIII/decidra/issues
"""

    home = Path.home()
    decidra_dir = home / '.decidra'
    readme_file = decidra_dir / 'README.md'

    try:
        readme_file.write_text(readme_content)
        print_success(f"创建 README: {readme_file}")
        return True
    except Exception as e:
        print_warning(f"创建 README 失败: {e}")
        return False


def print_next_steps():
    """打印后续步骤提示"""
    print()
    print_success("Decidra 配置完成!")
    print()
    print_info("下一步操作:")
    print_info("  1. 编辑配置文件:")
    print_info("     nano ~/.decidra/config.ini")
    print()
    print_info("  2. 验证配置:")
    print_info("     decidra config validate")
    print()
    print_info("  3. 测试富途连接:")
    print_info("     decidra futu test-connection")
    print()
    print_info("  4. 启动监控界面:")
    print_info("     decidra monitor start")
    print()
    print_info("详细文档: https://decidra.readthedocs.io/")
    print()


def main():
    """主函数"""
    print_info("开始 Decidra 安装后配置...")
    print()

    # 1. 验证安装
    if not verify_installation():
        print_error("安装验证失败，请重新安装 Decidra")
        return 1

    # 2. 初始化目录
    if not initialize_directories():
        print_error("目录初始化失败")
        return 1

    print()

    # 3. 复制配置模板
    if not copy_config_template():
        print_error("配置文件处理失败")
        return 1

    print()

    # 4. 创建 README
    create_readme()

    # 5. 打印后续步骤
    print_next_steps()

    return 0


if __name__ == '__main__':
    sys.exit(main())
