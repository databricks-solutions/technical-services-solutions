'use client';

import { useState, useEffect, useRef, useCallback, memo } from 'react';
import { MessageSquare, Send, FileText, Loader2, Sparkles, Info } from 'lucide-react';
import api from '@/lib/api';
import { Card, Button, ErrorMessage } from '@/components';
import { getErrorMessage } from '@/lib/utils';
import { truncateFilePath } from '@/lib/path-utils';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface FileItem {
  file_id: string;
  filename: string;
  dialect: string;
}

const STORAGE_KEY = 'migration_assistant_history';

function UnifiedAssistantView() {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [filesLoading, setFilesLoading] = useState(true);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [useAllFiles, setUseAllFiles] = useState(true);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadFiles();
    loadChatHistory();
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    // Save chat history to localStorage
    if (messages.length > 0) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    }
  }, [messages]);

  const loadFiles = async () => {
    try {
      setFilesLoading(true);
      const response = await api.listFiles();
      setFiles(response.files || []);
    } catch (err) {
      console.error('Failed to load files:', err);
    } finally {
      setFilesLoading(false);
    }
  };

  const loadChatHistory = () => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        // Convert timestamp strings back to Date objects
        setMessages(parsed.map((msg: any) => ({
          ...msg,
          timestamp: new Date(msg.timestamp)
        })));
      }
    } catch (err) {
      console.error('Failed to load chat history:', err);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleAsk = useCallback(async () => {
    if (!question.trim()) return;

    const targetFiles = useAllFiles 
      ? files 
      : files.filter(f => selectedFiles.includes(f.file_id));

    if (targetFiles.length === 0) {
      setError('Please select at least one file or choose "All Files"');
      return;
    }

    const userMessage: Message = {
      role: 'user',
      content: question,
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setQuestion('');
    setLoading(true);
    setError(null);

    try {
      let response;
      
      if (useAllFiles || targetFiles.length > 1) {
        // Multi-file query
        const fileIds = targetFiles.map(f => f.file_id);
        response = await api.queryMultipleAnalyzers(
          fileIds,
          userMessage.content,
          useAllFiles ? 'all' : 'multiple'
        );
      } else {
        // Single file query
        response = await api.queryAnalyzer(
          targetFiles[0].file_id,
          userMessage.content,
          {
            scope: 'single',
            file_ids: []
          }
        );
      }

      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer,
        timestamp: new Date()
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (err: any) {
      const errorMessage: Message = {
        role: 'assistant',
        content: `I encountered an error: ${getErrorMessage(err)}. Please try again or rephrase your question.`,
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  }, [question, files, selectedFiles, useAllFiles]);

  const handleClearHistory = () => {
    if (confirm('Are you sure you want to clear the chat history?')) {
      setMessages([]);
      localStorage.removeItem(STORAGE_KEY);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !loading) {
      e.preventDefault();
      handleAsk();
    }
  };

  const exampleQuestions = [
    "What are the most complex jobs in my data?",
    "Which tables have the most dependencies?",
    "Show me all scripts that read from the customer table",
    "What's the total lines of code across all files?",
    "Which objects are orphaned with no connections?"
  ];

  if (filesLoading) {
    return (
      <div className="grid lg:grid-cols-4 gap-6 animate-pulse">
        {/* Sidebar Skeleton */}
        <Card className="lg:col-span-1 h-fit">
          <div className="flex items-center justify-between mb-4">
            <div className="h-5 bg-gray-200 rounded w-24" />
            <div className="w-4 h-4 bg-gray-200 rounded" />
          </div>
          <div className="space-y-3 mb-4">
            {[1, 2].map((i) => (
              <div key={i} className="flex items-center space-x-2 p-2 rounded">
                <div className="w-4 h-4 bg-gray-200 rounded-full" />
                <div className="flex-1">
                  <div className="h-4 bg-gray-200 rounded w-20 mb-1" />
                  <div className="h-3 bg-gray-200 rounded w-16" />
                </div>
              </div>
            ))}
          </div>
          <div className="space-y-2 border-t pt-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-start space-x-2 p-2 rounded">
                <div className="w-4 h-4 bg-gray-200 rounded mt-0.5" />
                <div className="flex-1">
                  <div className="h-4 bg-gray-200 rounded w-32 mb-1" />
                  <div className="h-3 bg-gray-200 rounded w-20" />
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Main Chat Area Skeleton */}
        <div className="lg:col-span-3">
          <Card className="h-[calc(100vh-300px)] flex flex-col">
            <div className="flex-1 p-6">
              <div className="text-center py-12">
                <div className="w-16 h-16 bg-gray-200 rounded-full mx-auto mb-4" />
                <div className="h-6 bg-gray-200 rounded w-64 mx-auto mb-2" />
                <div className="h-4 bg-gray-200 rounded w-96 mx-auto mb-6" />
                <div className="space-y-2 max-w-xl mx-auto">
                  {[1, 2, 3, 4].map((i) => (
                    <div key={i} className="h-12 bg-gray-200 rounded-lg" />
                  ))}
                </div>
              </div>
            </div>
            <div className="border-t p-4 bg-gray-50">
              <div className="flex space-x-2">
                <div className="flex-1 h-20 bg-gray-200 rounded-lg" />
                <div className="w-20 h-20 bg-gray-200 rounded-lg" />
              </div>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <Card className="p-12 text-center">
        <Sparkles className="w-16 h-16 mx-auto mb-4 text-gray-300" />
        <h3 className="text-xl font-bold text-gray-900 mb-2">No Files Uploaded Yet</h3>
        <p className="text-gray-600 mb-6">
          Upload some analyzer files in the Files tab to start asking questions with AI
        </p>
      </Card>
    );
  }

  return (
    <div className="grid lg:grid-cols-4 gap-6">
      {/* Sidebar - File Selection */}
      <Card className="lg:col-span-1 h-fit sticky top-24">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-gray-900">Ask About:</h3>
          <Info className="w-4 h-4 text-gray-400" />
        </div>

        <div className="space-y-3 mb-4">
          <label className="flex items-center space-x-2 cursor-pointer p-2 rounded hover:bg-gray-50">
            <input
              type="radio"
              checked={useAllFiles}
              onChange={() => setUseAllFiles(true)}
              className="text-blue-600 focus:ring-blue-500"
            />
            <div className="flex-1">
              <span className="text-sm font-medium text-gray-900">All Files</span>
              <span className="text-xs text-gray-500 block">({files.length} files)</span>
            </div>
          </label>

          <label className="flex items-center space-x-2 cursor-pointer p-2 rounded hover:bg-gray-50">
            <input
              type="radio"
              checked={!useAllFiles}
              onChange={() => setUseAllFiles(false)}
              className="text-blue-600 focus:ring-blue-500"
            />
            <div className="flex-1">
              <span className="text-sm font-medium text-gray-900">Specific Files</span>
              <span className="text-xs text-gray-500 block">
                {selectedFiles.length > 0 ? `${selectedFiles.length} selected` : 'None selected'}
              </span>
            </div>
          </label>
        </div>

        {!useAllFiles && (
          <div className="space-y-2 max-h-96 overflow-y-auto border-t pt-4">
            <p className="text-xs text-gray-500 mb-2">Select files to query:</p>
            {files.map((file) => (
              <label key={file.file_id} className="flex items-start space-x-2 cursor-pointer p-2 rounded hover:bg-gray-50">
                <input
                  type="checkbox"
                  checked={selectedFiles.includes(file.file_id)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedFiles([...selectedFiles, file.file_id]);
                    } else {
                      setSelectedFiles(selectedFiles.filter(id => id !== file.file_id));
                    }
                  }}
                  className="mt-0.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 break-words" title={file.filename}>{truncateFilePath(file.filename)}</p>
                  <p className="text-xs text-gray-500 capitalize">{file.dialect}</p>
                </div>
              </label>
            ))}
          </div>
        )}

        {messages.length > 0 && (
          <button
            onClick={handleClearHistory}
            className="mt-4 w-full text-sm text-red-600 hover:text-red-800 py-2 text-center"
          >
            Clear History
          </button>
        )}
      </Card>

      {/* Main Chat Area */}
      <div className="lg:col-span-3 space-y-4">
        <Card className="h-[calc(100vh-300px)] flex flex-col">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {messages.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <MessageSquare className="w-16 h-16 mx-auto mb-4 text-gray-300" />
                <p className="text-lg font-medium mb-2">Ask me anything about your data!</p>
                <p className="text-sm mb-6">I can answer questions about your uploaded analyzer files</p>

                <div className="mt-8 text-left max-w-xl mx-auto">
                  <p className="text-sm font-medium text-gray-700 mb-3">Example questions:</p>
                  <div className="space-y-2">
                    {exampleQuestions.map((example, idx) => (
                      <button
                        key={idx}
                        onClick={() => setQuestion(example)}
                        className="w-full text-left text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 p-3 rounded-lg transition-colors border border-transparent hover:border-blue-200"
                      >
                        <Sparkles className="w-3 h-3 inline mr-2" />
                        {example}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <>
                {messages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-lg px-4 py-3 ${
                        msg.role === 'user'
                          ? 'bg-blue-600 text-white'
                          : 'bg-gray-100 text-gray-900'
                      }`}
                    >
                      <p className="text-sm whitespace-pre-wrap break-words">{msg.content}</p>
                      <p className={`text-xs mt-2 ${
                        msg.role === 'user' ? 'text-blue-100' : 'text-gray-500'
                      }`}>
                        {msg.timestamp.toLocaleTimeString()}
                      </p>
                    </div>
                  </div>
                ))}
                {loading && (
                  <div className="flex justify-start">
                    <div className="bg-gray-100 rounded-lg px-4 py-3">
                      <Loader2 className="w-5 h-5 animate-spin text-gray-600" />
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          {/* Input */}
          <div className="border-t p-4 bg-gray-50">
            {error && (
              <div className="mb-3">
                <ErrorMessage message={error} />
              </div>
            )}
            <div className="flex space-x-2">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={handleKeyPress}
                placeholder="Ask a question about your data... (Press Enter to send, Shift+Enter for new line)"
                className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-none"
                rows={2}
                disabled={loading}
              />
              <Button
                onClick={handleAsk}
                disabled={!question.trim() || loading}
                className="px-6 self-end"
              >
                {loading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Send className="w-5 h-5" />
                )}
              </Button>
            </div>
            <p className="text-xs text-gray-500 mt-2">
              {useAllFiles 
                ? `Querying across all ${files.length} files` 
                : `Querying ${selectedFiles.length} selected file(s)`}
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}

// Export memoized version for better performance
export default memo(UnifiedAssistantView);

