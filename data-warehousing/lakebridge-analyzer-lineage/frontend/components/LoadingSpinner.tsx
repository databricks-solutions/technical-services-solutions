import { Loader2 } from 'lucide-react';

interface LoadingSpinnerProps {
  size?: number;
  className?: string;
  text?: string;
}

export default function LoadingSpinner({ 
  size = 24, 
  className = '', 
  text 
}: LoadingSpinnerProps) {
  return (
    <div className={`flex flex-col items-center justify-center ${className}`}>
      <Loader2 className="animate-spin text-blue-600" size={size} />
      {text && <p className="mt-2 text-sm text-gray-600">{text}</p>}
    </div>
  );
}



