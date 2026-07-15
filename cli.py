#!/usr/bin/env python3
"""
Decidra 项目命令行工具

基于 click 框架的统一命令行接口，提供测试、配置管理等功能。
"""

import os
import sys
import json
import subprocess
import unittest
import configparser
import traceback
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

import click
from colorama import init, Fore, Style

# 初始化colorama，支持跨平台彩色输出
init(autoreset=True)

try:
    from decidra.api.futu import FutuConfig, FutuClient, create_client
    from decidra.utils.global_vars import config, PATH_CONFIG, get_config_manager
except ImportError as e:
    print(f"Import error: {e}")
    FutuConfig = None
    FutuClient = None
    create_client = None
    config = None
    get_config_manager = None



def print_success(message: str):
    """打印成功信息"""
    click.echo(f"{Fore.GREEN}✓ {message}{Style.RESET_ALL}")


def print_error(message: str):
    """打印错误信息"""
    click.echo(f"{Fore.RED}✗ {message}{Style.RESET_ALL}")


def print_warning(message: str):
    """打印警告信息"""
    click.echo(f"{Fore.YELLOW}⚠ {message}{Style.RESET_ALL}")


def print_info(message: str):
    """打印信息"""
    click.echo(f"{Fore.CYAN}ℹ {message}{Style.RESET_ALL}")


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).parent.parent


def load_config_ini(config_path: Optional[str] = None) -> Dict[str, Any]:
    """从config.ini加载配置（兼容性函数，建议使用新的配置管理器）
    
    Args:
        config_path: 配置文件路径，如果为None则使用默认路径
        
    Returns:
        解析后的配置字典
    """
    # 优先使用新的配置管理器
    if get_config_manager is not None:
        try:
            config_manager = get_config_manager()
            if config_path is None:
                # 使用默认配置
                return config_manager._config_data.copy()
            else:
                # 使用指定路径创建新的配置管理器实例
                from decidra.utils.config_manager import ConfigManager
                custom_manager = ConfigManager(Path(config_path).parent)
                return custom_manager._config_data.copy()
        except Exception as e:
            print_warning(f"新配置管理器不可用，使用传统方式: {e}")
    
    # 传统配置加载方式（向后兼容）
    if config_path is None:
        config_path = get_project_root() / 'src' / '.runtime' / 'config' / 'config.ini'
    else:
        config_path = Path(config_path)
    
    config_dict = {}
    
    if config_path.exists():
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path)
            
            # 转换为嵌套字典
            for section_name in parser.sections():
                config_dict[section_name] = dict(parser[section_name])
                
            print_info(f"已加载配置文件: {config_path}")
        except Exception as e:
            print_warning(f"读取配置文件失败: {e}")
    else:
        print_warning(f"配置文件不存在: {config_path}")
    
    return config_dict


def get_futu_defaults_from_config() -> Dict[str, Any]:
    """从config.ini获取富途API的默认配置"""
    # 优先使用新的配置管理器
    if get_config_manager is not None:
        try:
            config_manager = get_config_manager()
            futu_config = config_manager.get_futu_config()
            return {
                'host': futu_config['host'],
                'port': futu_config['port'],
                'websocketport': futu_config['websocket_port'],
                'trdenv': futu_config['trd_env']
            }
        except Exception as e:
            print_warning(f"新配置管理器获取配置失败，使用传统方式: {e}")
    
    # 传统方式获取配置
    config_dict = load_config_ini()
    
    defaults = {
        'host': '127.0.0.1',
        'port': 11111,
        'websocketport': 33333,
        'trdenv': 'SIMULATE'
    }
    
    # 从FutuOpenD.Config节读取配置
    if 'FutuOpenD.Config' in config_dict:
        futu_config = config_dict['FutuOpenD.Config']
        if 'host' in futu_config:
            defaults['host'] = futu_config['host']
        if 'port' in futu_config:
            defaults['port'] = int(futu_config['port'])
        if 'websocketport' in futu_config:
            defaults['websocketport'] = int(futu_config['websocketport'])
        if 'trdenv' in futu_config:
            defaults['trdenv'] = futu_config['trdenv']
    
    return defaults


def run_tests(test_module: str, verbosity: int = 2) -> bool:
    """运行指定的测试模块"""
    try:
        # 构建测试命令 - 进入src目录运行测试
        cmd = [sys.executable, '-m', 'unittest', test_module, '-v' if verbosity >= 2 else '']
        cmd = [c for c in cmd if c]  # 移除空字符串
        
        print_info(f"运行测试: {test_module}")
        
        # 运行测试 - 在src目录下运行
        result = subprocess.run(
            cmd,
            cwd=get_project_root() / 'src',
            capture_output=True,
            text=True
        )
        
        # 输出结果
        if result.stdout:
            click.echo(result.stdout)
        if result.stderr:
            click.echo(result.stderr, err=True)
        
        # 返回测试结果
        success = result.returncode == 0
        if success:
            print_success(f"测试 {test_module} 通过")
        else:
            print_error(f"测试 {test_module} 失败")
        
        return success
        
    except Exception as e:
        print_error(f"运行测试时出错: {e}")
        return False


@click.group()
@click.version_option(version='1.0.0', prog_name='Decidra CLI')
def cli():
    """
    Decidra 项目命令行工具
    
    提供测试、配置管理、富途API等功能的统一命令行接口。
    """
    pass


# ================== 测试相关命令 ==================

@cli.group()
def test():
    """测试相关命令"""
    pass


@test.command('test-unit')
@click.option('--verbose', '-v', is_flag=True, help='详细输出')
def test_unit(verbose: bool):
    """运行富途API单元测试"""
    print_info("开始运行富途API单元测试...")
    success = run_tests('tests.test_futu_api', verbosity=2 if verbose else 1)
    
    if success:
        print_success("单元测试全部通过！")
        sys.exit(0)
    else:
        print_error("单元测试失败！")
        sys.exit(1)


@test.command('test-integration')
@click.option('--verbose', '-v', is_flag=True, help='详细输出')
@click.option('--enable', is_flag=True, help='启用集成测试（需要FutuOpenD环境）')
def test_integration(verbose: bool, enable: bool):
    """运行富途API集成测试"""
    if enable:
        # 设置环境变量启用集成测试
        os.environ['FUTU_TEST_ENABLED'] = 'true'
        print_warning("已启用集成测试，请确保FutuOpenD正在运行")
    
    print_info("开始运行富途API集成测试...")
    success = run_tests('tests.test_futu_integration', verbosity=2 if verbose else 1)
    
    if success:
        print_success("集成测试完成！")
    else:
        print_error("集成测试失败！")
    
    sys.exit(0 if success else 1)


@test.command('test-config')
@click.option('--verbose', '-v', is_flag=True, help='详细输出')
def test_config_manager(verbose: bool):
    """运行配置管理器测试"""
    print_info("开始运行配置管理器测试...")
    success = run_tests('tests.test_config_manager', verbosity=2 if verbose else 1)
    
    if success:
        print_success("配置管理器测试通过！")
        sys.exit(0)
    else:
        print_error("配置管理器测试失败！")
        sys.exit(1)


# ================== 富途API相关命令 ==================

@cli.group()
def futu():
    """富途API相关命令"""
    if FutuConfig is None:
        print_error("富途API模块未找到，请检查项目设置")
        sys.exit(1)


@futu.command('config')
@click.option('--host', help='FutuOpenD主机地址')
@click.option('--port', type=int, help='FutuOpenD端口')
@click.option('--websocketport', type=int, help='WebSocket端口')
@click.option('--password', help='交易密码（可选）')
@click.option('--env', type=click.Choice(['SIMULATE', 'REAL']), help='交易环境')
@click.option('--show-only', is_flag=True, help='仅显示当前配置，不修改')
def futu_config(host: Optional[str], port: Optional[int], websocketport: Optional[int], 
                password: Optional[str], env: Optional[str], show_only: bool):
    """管理富途API配置文件"""
    try:
        # 配置文件路径
        config_path = get_project_root() / 'src' / '.runtime' / 'config' / 'config.ini'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 读取现有配置
        config_dict = load_config_ini()
        current_defaults = get_futu_defaults_from_config()
        
        # 如果只是显示配置
        if show_only:
            click.echo(f"{Fore.CYAN}当前富途API配置:{Style.RESET_ALL}")
            click.echo("="*40)
            click.echo(f"  配置文件: {config_path}")
            click.echo(f"  主机地址: {current_defaults['host']}")
            click.echo(f"  端口: {current_defaults['port']}")
            click.echo(f"  WebSocket端口: {current_defaults['websocketport']}")
            click.echo(f"  交易环境: {current_defaults['trdenv']}")
            
            # 显示其他配置节
            if config_dict:
                click.echo(f"\n其他配置节:")
                for section_name in config_dict.keys():
                    if section_name != 'FutuOpenD.Config':
                        click.echo(f"  [{section_name}]")
            return
        
        # 创建或更新配置
        parser = configparser.ConfigParser()
        if config_path.exists():
            parser.read(config_path)
        
        # 确保FutuOpenD.Config节存在
        if 'FutuOpenD.Config' not in parser:
            parser.add_section('FutuOpenD.Config')
        
        # 更新提供的配置值
        if host is not None:
            parser['FutuOpenD.Config']['host'] = host
        elif 'host' not in parser['FutuOpenD.Config']:
            parser['FutuOpenD.Config']['host'] = current_defaults['host']
            
        if port is not None:
            parser['FutuOpenD.Config']['port'] = str(port)
        elif 'port' not in parser['FutuOpenD.Config']:
            parser['FutuOpenD.Config']['port'] = str(current_defaults['port'])
            
        if websocketport is not None:
            parser['FutuOpenD.Config']['websocketport'] = str(websocketport)
        elif 'websocketport' not in parser['FutuOpenD.Config']:
            parser['FutuOpenD.Config']['websocketport'] = str(current_defaults['websocketport'])
            
        if env is not None:
            parser['FutuOpenD.Config']['trdenv'] = env
        elif 'trdenv' not in parser['FutuOpenD.Config']:
            parser['FutuOpenD.Config']['trdenv'] = current_defaults['trdenv']
            
        if password is not None:
            # 加密存储密码
            import hashlib
            password_md5 = hashlib.md5(password.encode()).hexdigest()
            if 'FutuOpenD.Credential' not in parser:
                parser.add_section('FutuOpenD.Credential')
            parser['FutuOpenD.Credential']['password_md5'] = password_md5
        
        # 保存配置文件
        with open(config_path, 'w', encoding='utf-8') as configfile:
            parser.write(configfile)
        
        print_success(f"配置已保存到: {config_path}")
        
        # 显示配置摘要
        click.echo(f"\n{Fore.CYAN}配置摘要:{Style.RESET_ALL}")
        click.echo(f"  主机地址: {parser['FutuOpenD.Config']['host']}")
        click.echo(f"  端口: {parser['FutuOpenD.Config']['port']}")
        click.echo(f"  WebSocket端口: {parser['FutuOpenD.Config']['websocketport']}")
        click.echo(f"  交易环境: {parser['FutuOpenD.Config']['trdenv']}")
        click.echo(f"  密码: {'已设置' if password else '未修改'}")
        
    except Exception as e:
        print_error(f"管理配置失败: {e}")
        sys.exit(1)


@futu.command('test-connection')
@click.option('--config', '-c', help='自定义配置文件路径')
@click.option('--host', help='FutuOpenD主机地址（覆盖配置文件）')
@click.option('--port', type=int, help='FutuOpenD端口（覆盖配置文件）')
def futu_test_connection(config: Optional[str], host: Optional[str], port: Optional[int]):
    """测试富途API连接"""
    try:
        # 获取配置默认值
        if config:
            config_dict = load_config_ini(config)
            print_info(f"使用自定义配置文件: {config}")
        else:
            config_dict = load_config_ini()
            print_info("使用默认配置文件")
        
        defaults = get_futu_defaults_from_config()
        
        # 使用命令行参数覆盖配置文件
        final_host = host if host is not None else defaults['host']
        final_port = port if port is not None else defaults['port']
        
        print_info(f"连接参数: {final_host}:{final_port}")
        print_info("正在测试连接...")
        
        if create_client:
            client = create_client(host=final_host, port=final_port)
            
            with client:
                print_success("连接成功！")
                print_info(f"客户端状态: {client}")
        else:
            print_warning("富途API模块未正确加载，跳过实际连接测试")
            print_info(f"测试参数: {final_host}:{final_port}")
            print_success("参数验证通过")
            
    except Exception as e:
        print_error(f"连接失败: {e}")
        print_warning("请确保:")
        click.echo("  1. FutuOpenD程序正在运行")
        click.echo("  2. 主机地址和端口正确")  
        click.echo("  3. 网络连接正常")
        click.echo("  4. 配置文件格式正确")
        sys.exit(1)


@futu.command('show-config')
@click.option('--config', '-c', help='自定义配置文件路径')
@click.option('--section', help='只显示指定配置节')
def futu_show_config(config: Optional[str], section: Optional[str]):
    """显示配置文件内容"""
    try:
        # 加载配置
        if config:
            config_dict = load_config_ini(config)
            config_path = config
        else:
            config_dict = load_config_ini()
            config_path = get_project_root() / 'src' / '.runtime' / 'config' / 'config.ini'
        
        click.echo(f"{Fore.CYAN}配置文件内容:{Style.RESET_ALL}")
        click.echo("="*50)
        click.echo(f"文件路径: {config_path}")
        click.echo("")
        
        if not config_dict:
            print_warning("配置文件为空或不存在")
            return
        
        # 显示指定节或所有节
        sections_to_show = [section] if section else config_dict.keys()
        
        for section_name in sections_to_show:
            if section_name in config_dict:
                click.echo(f"{Fore.YELLOW}[{section_name}]{Style.RESET_ALL}")
                for key, value in config_dict[section_name].items():
                    # 隐藏敏感信息
                    if 'password' in key.lower() or 'pwd' in key.lower():
                        value = '*' * len(value) if value else ''
                    click.echo(f"  {key} = {value}")
                click.echo("")
            elif section:
                print_error(f"配置节 [{section}] 不存在")
                
    except Exception as e:
        print_error(f"显示配置失败: {e}")
        sys.exit(1)


@futu.command('info')
@click.option('--config', '-c', help='自定义配置文件路径')
def futu_info(config: Optional[str]):
    """显示富途API配置信息"""
    try:
        # 从config.ini加载配置
        if config:
            config_dict = load_config_ini(config)
            print_info(f"使用自定义配置文件: {config}")
        else:
            config_dict = load_config_ini()
            print_info("使用默认配置文件")
        
        defaults = get_futu_defaults_from_config()
        
        # 显示富途API配置
        click.echo(f"\n{Fore.CYAN}富途API配置信息:{Style.RESET_ALL}")
        click.echo("="*40)
        click.echo(f"  主机地址: {defaults['host']}")
        click.echo(f"  端口: {defaults['port']}")
        click.echo(f"  WebSocket端口: {defaults['websocketport']}")
        click.echo(f"  交易环境: {defaults['trdenv']}")
        
        # 检查密码配置
        password_set = False
        if 'FutuOpenD.Credential' in config_dict:
            cred_config = config_dict['FutuOpenD.Credential']
            password_set = 'password_md5' in cred_config and cred_config['password_md5']
        click.echo(f"  交易密码: {'已设置' if password_set else '未设置'}")
        
        # 显示其他相关配置
        if 'tradingPreference' in config_dict:
            click.echo(f"\n{Fore.CYAN}交易偏好设置:{Style.RESET_ALL}")
            for key, value in config_dict['tradingPreference'].items():
                click.echo(f"  {key}: {value}")
        
        if 'email' in config_dict:
            click.echo(f"\n{Fore.CYAN}邮件配置:{Style.RESET_ALL}")
            for key, value in config_dict['email'].items():
                if 'password' in key.lower():
                    value = '*' * len(value) if value else '未设置'
                click.echo(f"  {key}: {value}")
        
        # 显示FutuOpenD状态检查
        click.echo(f"\n{Fore.CYAN}环境检查:{Style.RESET_ALL}")
        
        # 检查futu库
        try:
            import futu
            print_success(f"futu-api 库: 已安装 (v{getattr(futu, '__version__', '未知')})")
        except ImportError:
            print_error("futu-api 库: 未安装")
        
        # 检查配置管理器
        if get_config_manager is not None:
            try:
                config_manager = get_config_manager()
                validation = config_manager.validate_config()
                if validation.is_valid:
                    print_success("配置管理器: 可用且配置有效")
                else:
                    print_warning(f"配置管理器: 可用但配置有问题 ({len(validation.errors)} 错误)")
            except Exception as e:
                print_warning(f"配置管理器: 可用但初始化失败 ({e})")
        else:
            print_warning("配置管理器: 不可用")
        
        # 检查配置文件状态
        config_path = get_project_root() / 'src' / '.runtime' / 'config' / 'config.ini'
        if config_path.exists():
            print_success(f"配置文件: 存在")
        else:
            print_warning(f"配置文件: 不存在")
            
    except Exception as e:
        print_error(f"读取配置失败: {e}")
        sys.exit(1)


# ================== 配置管理命令 ==================

@cli.group()
def config_cmd():
    """配置管理命令"""
    pass


@config_cmd.command('app')
@click.option('--log-level', type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']),
              help='设置日志等级')
@click.option('--log-to-file/--no-log-to-file', default=None, help='是否输出日志到文件')
@click.option('--log-to-console/--no-log-to-console', default=None, help='是否输出日志到控制台')
@click.option('--debug-mode/--no-debug-mode', default=None, help='是否启用调试模式')
@click.option('--performance-monitoring/--no-performance-monitoring', default=None,
              help='是否启用性能监控')
@click.option('--show-only', is_flag=True, help='仅显示当前应用配置')
def app_config(log_level: Optional[str], log_to_file: Optional[bool], log_to_console: Optional[bool],
               debug_mode: Optional[bool], performance_monitoring: Optional[bool], show_only: bool):
    """管理应用配置（日志等级、调试模式等）"""
    try:
        if get_config_manager is None:
            print_error("配置管理器不可用")
            sys.exit(1)

        config_manager = get_config_manager()
        app_config = config_manager.get_application_config()

        # 如果只是显示配置
        if show_only:
            click.echo(f"{Fore.CYAN}当前应用配置:{Style.RESET_ALL}")
            click.echo("="*50)
            click.echo(f"  日志等级: {app_config['log_level']}")
            click.echo(f"  日志输出到文件: {'是' if app_config['log_to_file'] else '否'}")
            click.echo(f"  日志输出到控制台: {'是' if app_config['log_to_console'] else '否'}")
            click.echo(f"  日志文件最大大小: {app_config['log_file_max_size']} MB")
            click.echo(f"  日志文件备份数量: {app_config['log_file_backup_count']}")
            click.echo(f"  调试模式: {'启用' if app_config['debug_mode'] else '禁用'}")
            click.echo(f"  性能监控: {'启用' if app_config['performance_monitoring'] else '禁用'}")
            click.echo(f"  数据缓存TTL: {app_config['data_cache_ttl']} 秒")
            click.echo(f"  最大并发请求: {app_config['max_concurrent_requests']}")
            return

        # 检查是否有任何配置需要更新
        has_changes = any([
            log_level is not None,
            log_to_file is not None,
            log_to_console is not None,
            debug_mode is not None,
            performance_monitoring is not None
        ])

        if not has_changes:
            print_error("请指定要修改的配置项，或使用 --show-only 查看当前配置")
            return

        # 更新配置
        if log_level is not None:
            config_manager.set_config('Application', 'LogLevel', log_level)
            print_success(f"日志等级已设置为: {log_level}")

        if log_to_file is not None:
            config_manager.set_config('Application', 'LogToFile', 'true' if log_to_file else 'false')
            print_success(f"日志输出到文件: {'启用' if log_to_file else '禁用'}")

        if log_to_console is not None:
            config_manager.set_config('Application', 'LogToConsole', 'true' if log_to_console else 'false')
            print_success(f"日志输出到控制台: {'启用' if log_to_console else '禁用'}")

        if debug_mode is not None:
            config_manager.set_config('Application', 'DebugMode', 'true' if debug_mode else 'false')
            print_success(f"调试模式: {'启用' if debug_mode else '禁用'}")

        if performance_monitoring is not None:
            config_manager.set_config('Application', 'PerformanceMonitoring',
                                     'true' if performance_monitoring else 'false')
            print_success(f"性能监控: {'启用' if performance_monitoring else '禁用'}")

        # 保存配置
        if config_manager.save_config():
            print_success("配置已保存")
            print_warning("注意: 部分配置需要重启应用后生效")
        else:
            print_error("保存配置失败")
            sys.exit(1)

    except Exception as e:
        print_error(f"管理应用配置失败: {e}")
        sys.exit(1)


@config_cmd.command('validate')
@click.option('--fix', is_flag=True, help='自动修复可修复的配置问题')
def validate_config(fix: bool):
    """验证配置文件完整性"""
    try:
        if get_config_manager is None:
            print_error("新配置管理器不可用")
            sys.exit(1)
        
        config_manager = get_config_manager()
        result = config_manager.validate_config()
        
        print_info("配置验证结果:")
        click.echo("="*50)
        
        if result.is_valid:
            print_success("✓ 配置验证通过")
        else:
            print_error("✗ 配置验证失败")
        
        if result.errors:
            click.echo(f"\n{Fore.RED}错误 ({len(result.errors)}):{Style.RESET_ALL}")
            for error in result.errors:
                click.echo(f"  • {error}")
        
        if result.warnings:
            click.echo(f"\n{Fore.YELLOW}警告 ({len(result.warnings)}):{Style.RESET_ALL}")
            for warning in result.warnings:
                click.echo(f"  • {warning}")
        
        if fix and not result.is_valid:
            print_info("\n尝试自动修复配置...")
            # 这里可以添加自动修复逻辑
            print_warning("自动修复功能暂未实现")
        
        sys.exit(0 if result.is_valid else 1)
        
    except Exception as e:
        print_error(f"配置验证失败: {e}")
        sys.exit(1)


@config_cmd.command('summary')
@click.option('--verbose', '-v', is_flag=True, help='详细输出')
def config_summary(verbose: bool):
    """显示配置摘要信息"""
    try:
        if get_config_manager is None:
            print_error("新配置管理器不可用")
            sys.exit(1)
        
        config_manager = get_config_manager()
        summary = config_manager.get_config_summary()
        
        click.echo(f"{Fore.CYAN}配置摘要信息{Style.RESET_ALL}")
        click.echo("="*50)
        
        click.echo(f"配置目录: {summary['config_dir']}")
        click.echo(f"配置文件: {summary['config_file']}")
        click.echo(f"配置文件存在: {'是' if summary['config_exists'] else '否'}")
        click.echo(f"配置节数量: {len(summary['sections'])}")
        
        if summary['env_overrides']:
            click.echo(f"环境变量覆盖: {len(summary['env_overrides'])} 个")
        
        if verbose:
            click.echo(f"\n配置节列表:")
            for section in summary['sections']:
                click.echo(f"  • {section}")
            
            if summary['env_overrides']:
                click.echo(f"\n环境变量覆盖:")
                for env_section in summary['env_overrides']:
                    click.echo(f"  • {env_section}")
        
        # 显示验证结果
        validation = summary['validation']
        click.echo(f"\n配置验证: {'通过' if validation.is_valid else '失败'}")
        if validation.errors:
            click.echo(f"  错误数量: {len(validation.errors)}")
        if validation.warnings:
            click.echo(f"  警告数量: {len(validation.warnings)}")
        
        click.echo(f"\n最后加载时间: {summary['last_loaded']}")
        
    except Exception as e:
        print_error(f"获取配置摘要失败: {e}")
        sys.exit(1)


@config_cmd.command('reload')
def reload_config():
    """重新加载配置"""
    try:
        if get_config_manager is None:
            print_error("新配置管理器不可用")
            sys.exit(1)
        
        print_info("重新加载配置...")
        config_manager = get_config_manager()
        config_manager.reload_config()
        print_success("配置重新加载成功")
        
        # 显示重新加载后的验证结果
        result = config_manager.validate_config()
        if result.is_valid:
            print_success("配置验证通过")
        else:
            print_warning(f"配置验证失败: {len(result.errors)} 个错误")
        
    except Exception as e:
        print_error(f"重新加载配置失败: {e}")
        sys.exit(1)


# 将config_cmd添加到主CLI组
cli.add_command(config_cmd, name='config')


# ================== 项目信息命令 ==================

@cli.command('init-config')
def init_config():
    """初始化默认配置文件"""
    try:
        config_path = get_project_root() / 'src' / '.runtime' / 'config' / 'config.ini'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        if config_path.exists():
            if not click.confirm(f"配置文件已存在 ({config_path})，是否覆盖？"):
                print_info("取消操作")
                return
        
        # 创建默认配置
        parser = configparser.ConfigParser()
        
        # FutuOpenD配置
        parser.add_section('FutuOpenD.Config')
        parser['FutuOpenD.Config']['host'] = '127.0.0.1'
        parser['FutuOpenD.Config']['port'] = '11111'
        parser['FutuOpenD.Config']['websocketport'] = '33333'
        parser['FutuOpenD.Config']['trdenv'] = 'SIMULATE'
        
        # 交易偏好设置
        parser.add_section('tradingPreference')
        parser['tradingPreference']['ordersize'] = '100'
        parser['tradingPreference']['ordertype'] = 'NORMAL'
        parser['tradingPreference']['autonormalize'] = 'true'
        parser['tradingPreference']['maxpositions'] = '10'
        parser['tradingPreference']['positionsizemethod'] = 'dynamic'
        
        # 回测佣金设置
        parser.add_section('backtest.commission')
        parser['backtest.commission']['hk'] = '0.0008'
        parser['backtest.commission']['us'] = '0.0049'
        parser['backtest.commission']['cn'] = '0.0008'
        
        # 邮件配置（示例）
        parser.add_section('email')
        parser['email']['smtpserver'] = 'smtp.gmail.com'
        parser['email']['smtpport'] = '587'
        parser['email']['emailuser'] = ''
        parser['email']['emailpass'] = ''
        parser['email']['emailto'] = ''
        
        # 保存配置文件
        with open(config_path, 'w', encoding='utf-8') as configfile:
            parser.write(configfile)
        
        print_success(f"默认配置文件已创建: {config_path}")
        click.echo("\n提示:")
        click.echo("  1. 使用 'python src/cli.py futu config' 更新富途API配置")
        click.echo("  2. 手动编辑配置文件以设置邮件凭证")
        click.echo("  3. 使用 'python src/cli.py futu show-config' 查看当前配置")
        
    except Exception as e:
        print_error(f"创建配置文件失败: {e}")
        sys.exit(1)


@cli.command()
def info():
    """显示项目信息"""
    project_root = get_project_root()
    
    click.echo(f"{Fore.CYAN}Decidra 项目信息{Style.RESET_ALL}")
    click.echo("="*40)
    click.echo(f"项目根目录: {project_root}")
    click.echo(f"Python版本: {sys.version}")
    
    # 检查关键文件
    key_files = [
        'requirements.txt',
        'README.md',
        'src/api/futu.py',
        'src/tests/test_futu_api.py',
        'src/.runtime/config/config.ini'
    ]
    
    click.echo(f"\n关键文件状态:")
    for file_path in key_files:
        full_path = project_root / file_path
        if full_path.exists():
            print_success(f"{file_path}")
        else:
            print_error(f"{file_path} (缺失)")
    
    # 检查配置状态
    click.echo(f"\n配置状态:")
    config_dict = load_config_ini()
    if config_dict:
        print_success("配置文件已加载")
        click.echo(f"  配置节数量: {len(config_dict)}")
        if 'FutuOpenD.Config' in config_dict:
            print_success("富途API配置: 已设置")
        else:
            print_warning("富途API配置: 未设置")
    else:
        print_warning("配置文件: 未找到或为空")
        click.echo("  运行 'python src/cli.py init-config' 创建默认配置")
    
    # 检查富途API
    click.echo(f"\n富途API状态:")
    try:
        import futu
        print_success("futu-api 库已安装")
        click.echo(f"  版本: {getattr(futu, '__version__', '未知')}")
    except ImportError:
        print_error("futu-api 库未安装")
    
    # 检查测试环境
    click.echo(f"\n测试环境:")
    if os.getenv('FUTU_TEST_ENABLED', 'false').lower() == 'true':
        print_success("集成测试已启用")
        click.echo(f"  主机: {os.getenv('FUTU_HOST', '127.0.0.1')}")
        click.echo(f"  端口: {os.getenv('FUTU_PORT', '11111')}")
    else:
        print_warning("集成测试未启用")
        click.echo("  使用 --enable 选项启用集成测试")


@cli.command()
def env():
    """显示环境变量信息"""
    click.echo(f"{Fore.CYAN}环境变量信息{Style.RESET_ALL}")
    click.echo("="*30)
    
    # 富途相关环境变量
    futu_env_vars = [
        'FUTU_TEST_ENABLED',
        'FUTU_HOST',
        'FUTU_PORT', 
        'FUTU_TRADE_PWD',
        'FUTU_TRD_ENV',
        'FUTU_TIMEOUT',
        'FUTU_ENCRYPT',
        'FUTU_LOG_LEVEL'
    ]
    
    click.echo(f"富途API环境变量:")
    for var in futu_env_vars:
        value = os.getenv(var)
        if value:
            if 'PWD' in var:  # 隐藏密码
                value = '*' * len(value)
            print_success(f"{var} = {value}")
        else:
            print_warning(f"{var} = 未设置")


# ================== 监控命令组 ==================

@cli.group()
def monitor():
    """股票监控界面相关命令"""
    pass


@monitor.command('start')
@click.option('--stocks', help='监控股票列表，用逗号分隔，如: HK.00700,HK.09988,US.AAPL')
@click.option('--refresh', type=int, default=10, help='数据刷新间隔(秒)，默认10秒')
@click.option('--mode', type=click.Choice(['auto', 'realtime', 'snapshot']), 
              default='auto', help='刷新模式: auto(自动)/realtime(实时)/snapshot(快照)')
def start_monitor(stocks: Optional[str], refresh: int, mode: str):
    """启动股票监控界面
    
    启动基于Textual的终端监控界面，支持实时股票数据展示和分析。
    """
    import signal
    import threading
    import time
    
    app = None
    
    # 退出信号计数器和标志
    exit_signal_count = 0
    should_exit = False
    
    def signal_handler(signum, frame):
        """递进式信号处理器"""
        nonlocal exit_signal_count, should_exit
        exit_signal_count += 1
        
        if exit_signal_count == 1:
            print_warning(f"接收到信号 {signum}，正在优雅退出...")
            if app:
                try:
                    if hasattr(app, '_is_quitting'):
                        app._is_quitting = True
                    app.exit()
                except Exception as e:
                    print_error(f"应用退出失败: {e}")
            
            # 设置5秒后强制退出的标志
            def set_force_exit():
                time.sleep(5)
                if exit_signal_count == 1:  # 如果5秒内没有新的信号
                    nonlocal should_exit
                    should_exit = True
                    print_info("优雅退出完成")
            
            threading.Thread(target=set_force_exit, daemon=True).start()
            
        elif exit_signal_count == 2:
            print_warning("再次接收到退出信号，强制结束清理...")
            should_exit = True
            # 不在信号处理器中调用 sys.exit()，而是设置标志
            
        else:  # >= 3次
            print_error("多次强制退出请求，立即终止程序")
            # 作为最后手段，使用 os._exit
            import os
            os._exit(1)
    
    def graceful_exit_timer():
        """优雅退出监控定时器"""
        time.sleep(8)
        if exit_signal_count == 0:  # 如果没有收到退出信号
            print_warning("程序退出耗时较长，按 Ctrl+C 可强制退出")
    
    try:
        # 注册信号处理器
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        print_info("正在启动股票监控界面...")
        
        # 导入monitor_app
        try:
            from decidra.monitor_app import MonitorApp
        except ImportError as e:
            print_error(f"无法导入监控应用: {e}")
            print_warning("请确保monitor_app.py文件存在且可访问")
            traceback.print_exc()
            sys.exit(1)
        
        # 设置环境变量（如果需要）
        if refresh != 10:
            os.environ['MONITOR_REFRESH_INTERVAL'] = str(refresh)
        
        if mode != 'auto':
            os.environ['MONITOR_REFRESH_MODE'] = mode
        
        if stocks:
            os.environ['MONITOR_STOCKS'] = stocks
            print_info(f"监控股票: {stocks}")
        
        print_info(f"刷新间隔: {refresh}秒")
        print_info(f"刷新模式: {mode}")
        print_info("启动监控界面...")
        
        # 创建并运行监控应用
        app = MonitorApp()
        
        # 如果提供了股票列表，更新默认监控股票
        if stocks:
            stock_list = [stock.strip() for stock in stocks.split(',')]
            app.monitored_stocks = stock_list
        
        print_success("监控界面已启动！")
        print_info("快捷键:")
        click.echo("  Q: 退出程序 A: 添加股票 D: 删除股票 N: 添加订单 Z/X/C: 切换标签页")
        click.echo("  Ctrl+C: 强制退出")
        
        # 启动监控定时器
        timer_thread = threading.Thread(target=graceful_exit_timer, daemon=True)
        timer_thread.start()
        
        # 运行应用
        app.run()
        
        print_info("监控界面已退出")
        
        # 检查是否需要强制退出
        if should_exit:
            print_info("强制退出模式")
            sys.exit(0)
        
        # 给程序少量时间完成基本清理
        print_info("等待资源清理完成...")
        time.sleep(2)
        
        print_success("程序正常退出")
        
    except KeyboardInterrupt:
        # 这个异常处理器可能不会被调用，因为我们已经注册了信号处理器
        print_info("用户中断")
        
    except Exception as e:
        print_error(f"启动监控界面失败: {e}")
        import traceback
        if os.getenv('DEBUG', 'false').lower() == 'true':
            traceback.print_exc()
        
    finally:
        # 确保程序能够退出
        if should_exit:
            print_info("执行强制退出...")
            sys.exit(0)
        
        print_info("清理完成，程序即将退出...")
        # 小延迟确保日志输出
        time.sleep(0.5)


@monitor.command('config')
@click.option('--add', help='添加股票到监控列表')
@click.option('--remove', help='从监控列表中删除股票')
@click.option('--list', 'list_stocks', is_flag=True, help='显示当前监控股票列表')
@click.option('--clear', is_flag=True, help='清空监控列表')
def monitor_config(add: Optional[str], remove: Optional[str], list_stocks: bool, clear: bool):
    """管理监控股票配置"""
    try:
        # 加载配置管理器
        if get_config_manager is None:
            print_error("配置管理器不可用")
            sys.exit(1)
        
        config_manager = get_config_manager()
        
        # 读取当前配置
        try:
            current_config = config_manager._config_data.copy()
            stocks_config = current_config.get('monitored_stocks', {})
            # 从配置格式转换为列表
            monitored_stocks = []
            if isinstance(stocks_config, dict):
                for key in sorted(stocks_config.keys()):
                    if key.startswith('stock_'):
                        monitored_stocks.append(stocks_config[key])
            else:
                monitored_stocks = stocks_config if isinstance(stocks_config, list) else []
        except:
            monitored_stocks = []
        
        # 执行操作
        if add:
            if add not in monitored_stocks:
                monitored_stocks.append(add)
                print_success(f"已添加股票: {add}")
            else:
                print_warning(f"股票已存在: {add}")
        
        elif remove:
            if remove in monitored_stocks:
                monitored_stocks.remove(remove)
                print_success(f"已删除股票: {remove}")
            else:
                print_warning(f"股票不存在: {remove}")
        
        elif clear:
            if click.confirm("确定要清空所有监控股票吗？"):
                monitored_stocks = []
                print_success("已清空监控股票列表")
            else:
                print_info("取消操作")
                return
        
        elif list_stocks:
            if monitored_stocks:
                print_success(f"当前监控股票 ({len(monitored_stocks)}只):")
                for i, stock in enumerate(monitored_stocks, 1):
                    click.echo(f"  {i}. {stock}")
            else:
                print_warning("监控列表为空")
            return
        
        else:
            print_error("请指定操作: --add, --remove, --list 或 --clear")
            return
        
        # 保存配置
        if add or remove or clear:
            # 更新配置管理器的内部数据
            try:
                # 确保 monitored_stocks 部分存在
                if 'monitored_stocks' not in config_manager._config_data:
                    config_manager._config_data['monitored_stocks'] = {}
                
                # 将股票列表转换为配置格式
                for i, stock in enumerate(monitored_stocks):
                    config_manager._config_data['monitored_stocks'][f'stock_{i}'] = stock
                
                # 清除旧的stock_*键
                keys_to_remove = []
                for key in config_manager._config_data['monitored_stocks'].keys():
                    if key.startswith('stock_') and int(key.split('_')[1]) >= len(monitored_stocks):
                        keys_to_remove.append(key)
                
                for key in keys_to_remove:
                    del config_manager._config_data['monitored_stocks'][key]
                
                config_manager.save_config()
                print_info("配置已更新")
            except Exception as e:
                print_error(f"保存配置失败: {e}")
            
            # 显示当前列表
            if monitored_stocks:
                click.echo(f"\n当前监控股票 ({len(monitored_stocks)}只):")
                for i, stock in enumerate(monitored_stocks, 1):
                    click.echo(f"  {i}. {stock}")
            else:
                click.echo("\n监控列表为空")
        
    except Exception as e:
        print_error(f"配置管理失败: {e}")
        sys.exit(1)





if __name__ == '__main__':
    cli() 