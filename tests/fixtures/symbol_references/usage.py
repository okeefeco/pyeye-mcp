"""Usage module — imports and exercises symbols from other modules in the fixture project."""

from module_a.config import Config as ConfigA
from module_b.config import Config as ConfigB
from unique import UniqueWidget, create_unique_widget

# Use module_a.Config
server_cfg = ConfigA(host="example.com", port=443)
url = server_cfg.get_url()

# Use module_b.Config
db_cfg = ConfigB(dsn="postgresql://localhost/mydb")
valid = db_cfg.is_valid()

# Use UniqueWidget
widget = UniqueWidget("hello")
rendered = widget.render()

# Use factory function
other_widget = create_unique_widget("world")
