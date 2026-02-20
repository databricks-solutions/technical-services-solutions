'use client';

import { useEffect, useRef, useCallback } from 'react';
import cytoscape from 'cytoscape';

interface CytoscapeGraphProps {
  elements: any[];
  stylesheet: any[];
  onInit?: (cy: any) => void;
  width: number;
  height: number;
}

export default function CytoscapeGraph({
  elements,
  stylesheet,
  onInit,
  width,
  height,
}: CytoscapeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<any>(null);
  const isInitializedRef = useRef(false);

  // Smart label visibility based on zoom level
  const updateLabelVisibility = useCallback((cy: any) => {
    const zoom = cy.zoom();
    
    // Hide labels at low zoom, show at high zoom
    if (zoom < 0.5) {
      // Very zoomed out - hide all labels
      cy.nodes().style('label', '');
      cy.edges().style('label', '');
    } else if (zoom < 1.0) {
      // Medium zoom - show node labels only
      cy.nodes().style('label', 'data(label)');
      cy.edges().style('label', '');
    } else {
      // Zoomed in - show all labels
      cy.nodes().style('label', 'data(label)');
      cy.edges().style('label', 'data(label)');
    }
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    // Only create instance once
    if (!cyRef.current) {
      try {
        console.log('[CytoscapeGraph] Initializing with', elements.length, 'elements');

        // Create new Cytoscape instance
        const cy = cytoscape({
          container: containerRef.current,
          elements: elements,
          style: stylesheet,
          minZoom: 0.1,
          maxZoom: 3,
          wheelSensitivity: 0.2,
        });

        cyRef.current = cy;

        // Add zoom event listener for smart label visibility
        cy.on('zoom', () => {
          updateLabelVisibility(cy);
        });

        // Add hover events to always show labels on hover
        cy.on('mouseover', 'node', (event: any) => {
          event.target.style('label', event.target.data('label'));
          event.target.style('z-index', 999);
        });

        cy.on('mouseout', 'node', (event: any) => {
          // Restore label visibility based on zoom
          updateLabelVisibility(cy);
          event.target.style('z-index', 'auto');
        });

        cy.on('mouseover', 'edge', (event: any) => {
          event.target.style('label', event.target.data('label'));
          event.target.style('z-index', 999);
        });

        cy.on('mouseout', 'edge', (event: any) => {
          // Restore label visibility based on zoom
          updateLabelVisibility(cy);
          event.target.style('z-index', 'auto');
        });

        // Initial label visibility
        updateLabelVisibility(cy);

        // Call initialization callback
        if (onInit) {
          onInit(cy);
        }

        isInitializedRef.current = true;
        console.log('[CytoscapeGraph] Initialization complete');
      } catch (error) {
        console.error('[CytoscapeGraph] Failed to initialize:', error);
      }
    } else {
      // Use imperative updates for better performance
      console.log('[CytoscapeGraph] Updating elements imperatively');
      const cy = cyRef.current;
      
      try {
        // Batch updates for performance
        cy.startBatch();
        
        // Remove all existing elements
        cy.elements().remove();
        
        // Add new elements
        cy.add(elements);
        
        cy.endBatch();
        
        // Re-apply label visibility
        updateLabelVisibility(cy);
        
        // Call onInit again for layout updates
        if (onInit) {
          onInit(cy);
        }
        
        console.log('[CytoscapeGraph] Update complete');
      } catch (error) {
        console.error('[CytoscapeGraph] Update failed:', error);
      }
    }
  }, [elements, stylesheet, onInit, updateLabelVisibility]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
        isInitializedRef.current = false;
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        display: 'block',
        backgroundColor: '#111827',
      }}
    />
  );
}

