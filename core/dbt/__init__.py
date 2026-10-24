# N.B.
# This will add to the package’s __path__ all subdirectories of directories on sys.path named after the package which effectively combines both modules into a single namespace (dbt.adapters)
# The matching statement is in plugins/postgres/dbt/__init__.py

from pkgutil import extend_path

# 合并不同发行包提供的 dbt 命名空间：本地 core 源码可与已安装的适配器、公共宏共同使用。
__path__ = extend_path(__path__, __name__)
