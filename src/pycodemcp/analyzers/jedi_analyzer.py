"""Jedi-based analyzer for Python code intelligence."""

import jedi
from pathlib import Path
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class JediAnalyzer:
    """Wrapper around Jedi for semantic Python analysis."""
    
    def __init__(self, project_path: str = "."):
        """Initialize the Jedi analyzer.
        
        Args:
            project_path: Root path of the project to analyze
        """
        self.project_path = Path(project_path)
        self.project = jedi.Project(path=self.project_path)
        logger.info(f"Initialized JediAnalyzer for {self.project_path}")
        
    def find_symbol(self, name: str, fuzzy: bool = False) -> List[Dict[str, Any]]:
        """Find symbol definitions in the project."""
        results = []
        
        try:
            search_results = self.project.search(name, all_scopes=True)
            
            for result in search_results:
                if not fuzzy and result.name != name:
                    continue
                    
                results.append(self._serialize_name(result))
                
        except Exception as e:
            logger.error(f"Error in find_symbol: {e}")
            
        return results
        
    def goto_definition(self, file: str, line: int, column: int) -> Optional[Dict[str, Any]]:
        """Get definition location from a position."""
        try:
            file_path = Path(file)
            if not file_path.exists():
                return None
                
            source = file_path.read_text()
            script = jedi.Script(source, path=file_path, project=self.project)
            definitions = script.goto(line, column)
            
            if definitions:
                return self._serialize_name(definitions[0], include_docstring=True)
                
        except Exception as e:
            logger.error(f"Error in goto_definition: {e}")
            
        return None
        
    def find_references(
        self, file: str, line: int, column: int, include_definitions: bool = True
    ) -> List[Dict[str, Any]]:
        """Find all references to a symbol."""
        results = []
        
        try:
            file_path = Path(file)
            if not file_path.exists():
                return results
                
            source = file_path.read_text()
            script = jedi.Script(source, path=file_path, project=self.project)
            references = script.get_references(line, column, include_builtins=False)
            
            for ref in references:
                if not include_definitions and ref.is_definition():
                    continue
                    
                serialized = self._serialize_name(ref)
                serialized["is_definition"] = ref.is_definition()
                results.append(serialized)
                
        except Exception as e:
            logger.error(f"Error in find_references: {e}")
            
        return results
        
    def get_completions(self, file: str, line: int, column: int) -> List[Dict[str, Any]]:
        """Get code completions at a position."""
        completions = []
        
        try:
            file_path = Path(file)
            if not file_path.exists():
                return completions
                
            source = file_path.read_text()
            script = jedi.Script(source, path=file_path, project=self.project)
            
            for completion in script.complete(line, column):
                completions.append({
                    "name": completion.name,
                    "complete": completion.complete,
                    "type": completion.type,
                    "description": completion.description,
                    "docstring": completion.docstring(),
                })
                
        except Exception as e:
            logger.error(f"Error in get_completions: {e}")
            
        return completions
        
    def get_signature_help(self, file: str, line: int, column: int) -> Optional[Dict[str, Any]]:
        """Get signature help for function calls."""
        try:
            file_path = Path(file)
            if not file_path.exists():
                return None
                
            source = file_path.read_text()
            script = jedi.Script(source, path=file_path, project=self.project)
            signatures = script.get_signatures(line, column)
            
            if signatures:
                sig = signatures[0]
                return {
                    "name": sig.name,
                    "params": [param.description for param in sig.params],
                    "index": sig.index,
                    "docstring": sig.docstring(),
                }
                
        except Exception as e:
            logger.error(f"Error in get_signature_help: {e}")
            
        return None
        
    def analyze_imports(self, file: str) -> List[Dict[str, Any]]:
        """Analyze imports in a file."""
        imports = []
        
        try:
            file_path = Path(file)
            if not file_path.exists():
                return imports
                
            source = file_path.read_text()
            script = jedi.Script(source, path=file_path, project=self.project)
            
            names = script.get_names(all_scopes=True, definitions=True, references=False)
            
            for name in names:
                if name.type in ["module", "import"]:
                    imports.append({
                        "name": name.name,
                        "full_name": name.full_name,
                        "line": name.line,
                        "column": name.column,
                        "description": name.description,
                    })
                    
        except Exception as e:
            logger.error(f"Error in analyze_imports: {e}")
            
        return imports
        
    def _serialize_name(self, name: jedi.api.classes.Name, include_docstring: bool = False) -> Dict[str, Any]:
        """Serialize a Jedi Name object to a dictionary."""
        result = {
            "name": name.name,
            "type": name.type,
            "line": name.line,
            "column": name.column,
            "description": name.description,
            "full_name": name.full_name,
        }
        
        if name.module_path:
            result["file"] = str(name.module_path)
            
        if include_docstring:
            result["docstring"] = name.docstring()
            
        return result