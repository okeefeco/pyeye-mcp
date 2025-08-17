"""Multi-project management for Python Code Intelligence."""

import jedi
from pathlib import Path
from typing import Dict, Optional, List, Set
import logging
from .cache import CodebaseWatcher, ProjectCache
from .namespace_resolver import NamespaceResolver

logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages multiple Python projects simultaneously."""
    
    def __init__(self, max_projects: int = 10):
        """Initialize the project manager.
        
        Args:
            max_projects: Maximum number of projects to keep in memory
        """
        self.projects: Dict[Path, jedi.Project] = {}
        self.watchers: Dict[Path, CodebaseWatcher] = {}
        self.caches: Dict[Path, ProjectCache] = {}
        self.access_order: List[Path] = []  # LRU tracking
        self.max_projects = max_projects
        
        # Project dependencies - maps project to its dependencies
        self.dependencies: Dict[Path, Set[Path]] = {}
        
        # Namespace resolver for distributed packages
        self.namespace_resolver = NamespaceResolver()
        
    def get_project(self, project_path: str, include_paths: List[str] = None) -> jedi.Project:
        """Get or create a Jedi project.
        
        Args:
            project_path: Main project path
            include_paths: Additional paths to include (e.g., local packages)
            
        Returns:
            Jedi project configured with all paths
        """
        main_path = Path(project_path).resolve()
        
        # Track access for LRU
        if main_path in self.access_order:
            self.access_order.remove(main_path)
        self.access_order.append(main_path)
        
        # Check if we need to create/update the project
        if main_path not in self.projects or self._needs_update(main_path, include_paths):
            self._create_project(main_path, include_paths)
            
        # Evict old projects if needed
        self._evict_if_needed()
        
        return self.projects[main_path]
        
    def _needs_update(self, main_path: Path, include_paths: List[str] = None) -> bool:
        """Check if project configuration has changed."""
        if main_path not in self.dependencies:
            return True
            
        current_deps = self.dependencies[main_path]
        new_deps = set(Path(p).resolve() for p in (include_paths or []))
        
        return current_deps != new_deps
        
    def _create_project(self, main_path: Path, include_paths: List[str] = None):
        """Create a new project with watchers and cache."""
        logger.info(f"Creating project for {main_path}")
        
        # Clean up old project if exists
        if main_path in self.projects:
            self._cleanup_project(main_path)
            
        # Configure project paths
        all_paths = [main_path]
        dep_paths = set()
        
        if include_paths:
            for path in include_paths:
                resolved = Path(path).resolve()
                if resolved.exists() and resolved.is_dir():
                    all_paths.append(resolved)
                    dep_paths.add(resolved)
                    logger.info(f"  Including dependency: {resolved}")
                    
        # Create Jedi project with all paths
        # Jedi's added_sys_path allows searching in multiple locations
        self.projects[main_path] = jedi.Project(
            path=main_path,
            added_sys_path=all_paths
        )
        
        # Store dependencies
        self.dependencies[main_path] = dep_paths
        
        # Create cache
        self.caches[main_path] = ProjectCache(ttl_seconds=300)
        
        # Set up watcher for main project
        def on_change(file_path):
            logger.info(f"File changed in {main_path}: {file_path}")
            # Invalidate this project's cache
            if main_path in self.caches:
                self.caches[main_path].invalidate()
            # Recreate Jedi project on next access
            if main_path in self.projects:
                del self.projects[main_path]
                
        watcher = CodebaseWatcher(str(main_path), on_change)
        watcher.start()
        self.watchers[main_path] = watcher
        
        # Optional: Watch dependency paths too
        for dep_path in dep_paths:
            dep_watcher = CodebaseWatcher(str(dep_path), on_change)
            dep_watcher.start()
            # Store with compound key
            self.watchers[dep_path] = dep_watcher
            
    def _cleanup_project(self, project_path: Path):
        """Clean up a project's resources."""
        logger.info(f"Cleaning up project {project_path}")
        
        # Stop watchers
        if project_path in self.watchers:
            self.watchers[project_path].stop()
            del self.watchers[project_path]
            
        # Stop dependency watchers
        if project_path in self.dependencies:
            for dep_path in self.dependencies[project_path]:
                if dep_path in self.watchers:
                    self.watchers[dep_path].stop()
                    del self.watchers[dep_path]
                    
        # Clear cache
        if project_path in self.caches:
            del self.caches[project_path]
            
        # Remove project
        if project_path in self.projects:
            del self.projects[project_path]
            
        # Clear dependencies
        if project_path in self.dependencies:
            del self.dependencies[project_path]
            
    def _evict_if_needed(self):
        """Evict least recently used projects if over limit."""
        while len(self.projects) > self.max_projects:
            # Remove least recently used
            lru_path = self.access_order.pop(0)
            logger.info(f"Evicting LRU project: {lru_path}")
            self._cleanup_project(lru_path)
            
    def get_cache(self, project_path: str) -> ProjectCache:
        """Get cache for a project."""
        main_path = Path(project_path).resolve()
        if main_path not in self.caches:
            self.caches[main_path] = ProjectCache()
        return self.caches[main_path]
        
    def search_all_projects(self, name: str) -> Dict[str, List]:
        """Search for a symbol across all active projects.
        
        Args:
            name: Symbol name to search for
            
        Returns:
            Dictionary mapping project paths to results
        """
        results = {}
        
        for project_path, project in self.projects.items():
            try:
                search_results = project.search(name, all_scopes=True)
                if search_results:
                    results[str(project_path)] = [
                        {
                            "name": r.name,
                            "file": str(r.module_path) if r.module_path else None,
                            "line": r.line,
                            "type": r.type,
                        }
                        for r in search_results
                    ]
            except Exception as e:
                logger.error(f"Error searching in {project_path}: {e}")
                
        return results
        
    def cleanup_all(self):
        """Clean up all projects."""
        for project_path in list(self.projects.keys()):
            self._cleanup_project(project_path)
            
        self.access_order.clear()


# Global project manager instance
_project_manager: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    """Get or create the global project manager."""
    global _project_manager
    if _project_manager is None:
        _project_manager = ProjectManager()
    return _project_manager