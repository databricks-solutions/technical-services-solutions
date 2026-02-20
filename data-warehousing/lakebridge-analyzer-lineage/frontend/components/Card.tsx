import { ReactNode, HTMLAttributes } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  className?: string;
  padding?: 'sm' | 'md' | 'lg';
  hover?: boolean;
}

export default function Card({ 
  children, 
  className = '', 
  padding = 'md',
  hover = false,
  ...rest
}: CardProps) {
  const paddingClasses = {
    sm: 'p-4',
    md: 'p-6',
    lg: 'p-8'
  };

  const hoverClass = hover ? 'transition-all hover:shadow-xl' : '';

  return (
    <div className={`bg-white shadow-lg ${paddingClasses[padding]} ${hoverClass} ${className}`} {...rest}>
      {children}
    </div>
  );
}



