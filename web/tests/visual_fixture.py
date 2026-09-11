"""Small synthetic visual observations shared by local contract tests."""
def observation(**changes):
    value = {'schema_version': 'visual-result/v1', 'kind': 'text', 'title': '合成页面',
        'status': 'complete', 'summary': '仅用于测试', 'text_blocks': [], 'facts': [],
        'tables': [], 'charts': [], 'interpretation': '', 'unresolved': []}
    value.update(changes)
    return value
