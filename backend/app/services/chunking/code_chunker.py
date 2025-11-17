"""
代码分片器
基于AST的智能代码分片，保持函数/类完整性
"""

from typing import List, Dict, Any, Optional
import re
import logging
from .base_chunker import BaseChunker, ChunkResult, ChunkingConfig
from .registry import register_chunker

logger = logging.getLogger(__name__)


@register_chunker("code")
class CodeChunker(BaseChunker):
    """代码专用分片器"""
    
    # 支持的代码文件类型
    CODE_EXTENSIONS = {
        'py', 'js', 'jsx', 'ts', 'tsx', 'java', 'cpp', 'c', 'h', 'hpp',
        'cs', 'go', 'rs', 'rb', 'php', 'swift', 'kt', 'scala', 'r',
        'lua', 'pl', 'sh', 'bash', 'sql', 'vue', 'svelte'
    }
    
    def can_handle(self, file_type: str, content: str) -> bool:
        """判断是否为代码文件"""
        return file_type.lower() in self.CODE_EXTENSIONS
    
    def get_priority(self) -> int:
        """高优先级（专用分片器）"""
        return 85
    
    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        智能分片代码文件
        
        Args:
            content: 代码内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        if not content or not content.strip():
            return []
        
        # 检测编程语言
        language = metadata.get('file_type', 'unknown') if metadata else 'unknown'
        
        # 尝试使用AST解析（目前仅支持Python）
        if language == 'py' and self.config.ast_parsing:
            try:
                return self._chunk_python_ast(content, metadata)
            except Exception as e:
                logger.warning(f"AST parsing failed, falling back to regex: {e}")
        
        # 降级到基于正则的分片
        return self._chunk_by_regex(content, language, metadata)
    
    def _chunk_python_ast(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        使用AST解析Python代码
        
        Args:
            content: Python代码
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        import ast
        
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            logger.error(f"Python syntax error: {e}")
            return self._chunk_by_regex(content, 'py', metadata)
        
        chunks = []
        lines = content.split('\n')
        
        # 提取imports（作为上下文）
        imports = self._extract_imports(tree, lines)
        
        chunk_index = 0
        
        # 遍历顶层节点
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # 提取函数/类的源代码
                start_line = node.lineno - 1
                end_line = node.end_lineno if hasattr(node, 'end_lineno') else start_line + 1
                
                # 获取完整的函数/类定义（包括装饰器）
                if hasattr(node, 'decorator_list') and node.decorator_list:
                    start_line = node.decorator_list[0].lineno - 1
                
                code_block = '\n'.join(lines[start_line:end_line])
                
                # 添加imports上下文
                full_content = f"{imports}\n\n{code_block}" if imports else code_block
                
                # **核心原则：每个函数/类是一个完整的分片单位，chunk_size 只是保底值**
                # 只有当单个函数/类本身超过 chunk_size 时，才对其进行二次切分
                if len(full_content) > self.config.chunk_size:
                    # 代码块超过 chunk_size，进一步分割
                    sub_chunks = self._split_large_code_block(full_content, node, metadata)
                    for sub_chunk in sub_chunks:
                        sub_chunk.chunk_index = chunk_index
                        chunks.append(sub_chunk)
                        chunk_index += 1
                else:
                    # 函数/类大小合适，作为一个完整分片
                    chunk = ChunkResult(
                        content=full_content,
                        metadata={
                            'chunker': 'code',
                            'language': 'python',
                            'node_type': node.__class__.__name__,
                            'name': node.name,
                            'lineno': node.lineno,
                            'has_imports': bool(imports),
                            **(metadata or {})
                        },
                        chunk_index=chunk_index,
                        completeness=True
                    )
                    chunks.append(self.enrich_metadata(chunk, metadata))
                    chunk_index += 1
        
        # 处理模块级代码（不在函数/类中的代码）
        module_code = self._extract_module_level_code(tree, lines)
        if module_code:
            chunk = ChunkResult(
                content=module_code,
                metadata={
                    'chunker': 'code',
                    'language': 'python',
                    'node_type': 'module',
                    **(metadata or {})
                },
                chunk_index=chunk_index,
                completeness=True
            )
            chunks.append(self.enrich_metadata(chunk, metadata))
        
        return chunks if chunks else self._chunk_by_regex(content, 'py', metadata)
    
    def _extract_imports(self, tree, lines: List[str]) -> str:
        """提取所有import语句"""
        import ast
        
        import_lines = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if hasattr(node, 'lineno'):
                    import_lines.append(lines[node.lineno - 1])
        
        return '\n'.join(import_lines)
    
    def _extract_module_level_code(self, tree, lines: List[str]) -> str:
        """提取模块级代码（不在函数/类中的代码）"""
        import ast
        
        # 获取所有函数/类的行号范围
        excluded_ranges = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno - 1
                end = node.end_lineno if hasattr(node, 'end_lineno') else start + 1
                if hasattr(node, 'decorator_list') and node.decorator_list:
                    start = node.decorator_list[0].lineno - 1
                excluded_ranges.append((start, end))
        
        # 提取不在这些范围内的代码
        module_lines = []
        for i, line in enumerate(lines):
            if not any(start <= i < end for start, end in excluded_ranges):
                # 排除import和空行
                if line.strip() and not line.strip().startswith(('import ', 'from ')):
                    module_lines.append(line)
        
        return '\n'.join(module_lines)
    
    def _split_large_code_block(
        self,
        code: str,
        node: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[ChunkResult]:
        """
        分割大的代码块，在合适的边界截断
        
        **核心原则：chunk_size 是硬性上限**
        - 在逻辑边界（函数、语句）处截断
        - 保持代码的可读性
        """
        lines = code.split('\n')
        chunks = []
        current_chunk = []
        current_size = 0
        
        # 识别代码块的结构（imports、函数签名、主体）
        import_lines = []
        signature_lines = []
        body_start = 0
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(('import ', 'from ')):
                import_lines.append(line)
            elif stripped.startswith(('def ', 'class ', 'async def ')):
                signature_lines.append(line)
                body_start = i + 1
                break
        
        # 确保每个分片都包含必要的上下文（imports + 签名）
        context = import_lines + signature_lines
        context_str = '\n'.join(context) if context else ''
        context_size = len(context_str) + 1 if context_str else 0
        
        # 分割函数体
        for i in range(body_start, len(lines)):
            line = lines[i]
            line_size = len(line) + 1  # +1 for newline
            
            # 检查是否超过 chunk_size
            if current_size + line_size > self.config.chunk_size and current_chunk:
                # 保存当前分片（包含上下文）
                chunk_content = context_str + '\n' + '\n'.join(current_chunk) if context_str else '\n'.join(current_chunk)
                
                chunk = ChunkResult(
                    content=chunk_content,
                    metadata={
                        'chunker': 'code',
                        'language': 'python',
                        'node_type': node.__class__.__name__,
                        'name': node.name,
                        'partial': True,
                        'has_context': bool(context_str),
                        **(metadata or {})
                    },
                    chunk_index=0,  # 将在外部设置
                    completeness=False
                )
                chunks.append(self.enrich_metadata(chunk, metadata))
                
                current_chunk = [line]
                current_size = context_size + line_size
            else:
                current_chunk.append(line)
                current_size += line_size
        
        # 保存最后一个分片
        if current_chunk:
            chunk_content = context_str + '\n' + '\n'.join(current_chunk) if context_str else '\n'.join(current_chunk)
            
            chunk = ChunkResult(
                content=chunk_content,
                metadata={
                    'chunker': 'code',
                    'language': 'python',
                    'node_type': node.__class__.__name__,
                    'name': node.name,
                    'partial': True,
                    'has_context': bool(context_str),
                    **(metadata or {})
                },
                chunk_index=0,
                completeness=False
            )
            chunks.append(self.enrich_metadata(chunk, metadata))
        
        return chunks
    
    def _chunk_by_regex(
        self,
        content: str,
        language: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[ChunkResult]:
        """
        使用正则表达式分片代码（降级方案）
        
        Args:
            content: 代码内容
            language: 编程语言
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        # 定义各语言的函数/类匹配模式
        patterns = {
            'py': r'(?:^|\n)((?:async\s+)?(?:def|class)\s+\w+[^\n]*:(?:\n(?:    |\t).*)*)',
            'js': r'(?:^|\n)((?:function|class|const|let|var)\s+\w+[^\n]*\{(?:[^{}]|\{[^{}]*\})*\})',
            'ts': r'(?:^|\n)((?:function|class|interface|type|const|let|var)\s+\w+[^\n]*\{(?:[^{}]|\{[^{}]*\})*\})',
            'java': r'(?:^|\n)((?:public|private|protected)?\s*(?:static)?\s*(?:class|interface|enum)\s+\w+[^\n]*\{(?:[^{}]|\{[^{}]*\})*\})',
            'cpp': r'(?:^|\n)((?:class|struct|namespace)\s+\w+[^\n]*\{(?:[^{}]|\{[^{}]*\})*\})',
            'go': r'(?:^|\n)(func\s+(?:\(\w+\s+\*?\w+\)\s+)?\w+[^\n]*\{(?:[^{}]|\{[^{}]*\})*\})',
        }
        
        pattern = patterns.get(language)
        
        if pattern:
            # 尝试按函数/类分割
            matches = list(re.finditer(pattern, content, re.MULTILINE))
            
            if matches:
                chunks = []
                for i, match in enumerate(matches):
                    code_block = match.group(1)
                    
                    # **核心原则：每个函数/类是一个完整的分片单位**
                    if len(code_block) > self.config.chunk_size:
                        # 代码块超过 chunk_size，按行分割
                        sub_chunks = self._split_by_lines(code_block, language, metadata)
                        chunks.extend(sub_chunks)
                    else:
                        # 函数/类大小合适，作为一个完整分片
                        chunk = ChunkResult(
                            content=code_block,
                            metadata={
                                'chunker': 'code',
                                'language': language,
                                'method': 'regex',
                                **(metadata or {})
                            },
                            chunk_index=i,
                            completeness=True
                        )
                        chunks.append(self.enrich_metadata(chunk, metadata))
                
                return chunks
        
        # 最终降级：按行分割
        return self._split_by_lines(content, language, metadata)
    
    def _split_by_lines(
        self,
        content: str,
        language: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[ChunkResult]:
        """按行分割代码"""
        lines = content.split('\n')
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_index = 0
        
        for line in lines:
            line_size = len(line) + 1
            
            if current_size + line_size > self.config.chunk_size and current_chunk:
                chunk = ChunkResult(
                    content='\n'.join(current_chunk),
                    metadata={
                        'chunker': 'code',
                        'language': language,
                        'method': 'lines',
                        **(metadata or {})
                    },
                    chunk_index=chunk_index,
                    completeness=False
                )
                chunks.append(self.enrich_metadata(chunk, metadata))
                chunk_index += 1
                
                current_chunk = [line]
                current_size = line_size
            else:
                current_chunk.append(line)
                current_size += line_size
        
        if current_chunk:
            chunk = ChunkResult(
                content='\n'.join(current_chunk),
                metadata={
                    'chunker': 'code',
                    'language': language,
                    'method': 'lines',
                    **(metadata or {})
                },
                chunk_index=chunk_index,
                completeness=False
            )
            chunks.append(self.enrich_metadata(chunk, metadata))
        
        return chunks

