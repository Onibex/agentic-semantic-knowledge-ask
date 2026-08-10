from abc import ABC, abstractmethod
from pathlib import Path


class FileStorageRepository(ABC):
    """
    Puerto (Interfaz) para el almacenamiento de archivos YAML.
    Cualquier implementación futura (Local, S3, Azure) debe heredar de esta clase.
    """

    @abstractmethod
    def save_file(self, file_path: str, content: str) -> str:
        pass


class LocalFileStorageRepository(FileStorageRepository):
    """
    Adaptador concreto que guarda los archivos en el disco duro local,
    respetando la estructura de carpetas de la Sección 4 del PDF.
    """

    def __init__(self, base_dir: str = "./ask_workspace"):
        self.base_dir = Path(base_dir)

    def save_file(self, relative_path: str, content: str) -> str:
        """
        Guarda el archivo creando los directorios intermedios si no existen.
        """
        full_path = self.base_dir / relative_path

        # Crear directorios si no existen (ej. ask/s4h/silver/sd/)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Escribir el contenido YAML
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        return str(full_path)


class AskPathBuilder:
    """
    Helper para construir las rutas deterministas según la Sección 4 del PDF.
    """

    @staticmethod
    def build_path(node) -> str:
        if node.layer == "bronze":
            # ej: ask/s4h/bronze/vbak.yaml
            return f"ask/{node.source_system}/bronze/{node.name.lower()}.yaml"
        else:
            # ej: ask/s4h/silver/sd/sales_order.yaml
            return f"ask/{node.source_system}/{node.layer}/{node.module.lower()}/{node.name.lower()}.yaml"
