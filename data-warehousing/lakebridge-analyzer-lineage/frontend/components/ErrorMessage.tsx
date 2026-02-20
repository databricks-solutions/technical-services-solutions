import { AlertCircle } from 'lucide-react';

interface ErrorMessageProps {
  title?: string;
  message: string;
  className?: string;
}

export default function ErrorMessage({ 
  title = 'Error', 
  message, 
  className = '' 
}: ErrorMessageProps) {
  return (
    <div className={`p-4 bg-red-50 border border-red-200 rounded-lg flex items-start space-x-3 ${className}`}>
      <AlertCircle className="w-5 h-5 text-red-600 mt-0.5 flex-shrink-0" />
      <div className="flex-1">
        <p className="font-semibold text-red-900">{title}</p>
        <p className="text-sm text-red-700 mt-1">{message}</p>
      </div>
    </div>
  );
}



