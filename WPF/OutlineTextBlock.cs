using System;
using System.Globalization;
using System.Windows;
using System.Windows.Media;

namespace RTtranslator_CS_Overlay
{
    public class OutlineTextBlock : FrameworkElement
    {
        public static readonly DependencyProperty TextProperty =
            DependencyProperty.Register("Text", typeof(string), typeof(OutlineTextBlock),
                new FrameworkPropertyMetadata(string.Empty, FrameworkPropertyMetadataOptions.AffectsRender | FrameworkPropertyMetadataOptions.AffectsMeasure));

        public static readonly DependencyProperty FontFamilyProperty =
            DependencyProperty.Register("FontFamily", typeof(FontFamily), typeof(OutlineTextBlock),
                new FrameworkPropertyMetadata(new FontFamily("MS Gothic"), FrameworkPropertyMetadataOptions.AffectsRender | FrameworkPropertyMetadataOptions.AffectsMeasure));

        public static readonly DependencyProperty FontSizeProperty =
            DependencyProperty.Register("FontSize", typeof(double), typeof(OutlineTextBlock),
                new FrameworkPropertyMetadata(14.0, FrameworkPropertyMetadataOptions.AffectsRender | FrameworkPropertyMetadataOptions.AffectsMeasure));

        public static readonly DependencyProperty FillProperty =
            DependencyProperty.Register("Fill", typeof(Brush), typeof(OutlineTextBlock),
                new FrameworkPropertyMetadata(Brushes.White, FrameworkPropertyMetadataOptions.AffectsRender));

        public static readonly DependencyProperty StrokeProperty =
            DependencyProperty.Register("Stroke", typeof(Brush), typeof(OutlineTextBlock),
                new FrameworkPropertyMetadata(Brushes.Black, FrameworkPropertyMetadataOptions.AffectsRender));

        public static readonly DependencyProperty StrokeThicknessProperty =
            DependencyProperty.Register("StrokeThickness", typeof(double), typeof(OutlineTextBlock),
                new FrameworkPropertyMetadata(2.5, FrameworkPropertyMetadataOptions.AffectsRender));

        public string Text
        {
            get { return (string)GetValue(TextProperty); }
            set { SetValue(TextProperty, value); }
        }

        public FontFamily FontFamily
        {
            get { return (FontFamily)GetValue(FontFamilyProperty); }
            set { SetValue(FontFamilyProperty, value); }
        }

        public double FontSize
        {
            get { return (double)GetValue(FontSizeProperty); }
            set { SetValue(FontSizeProperty, value); }
        }

        public Brush Fill
        {
            get { return (Brush)GetValue(FillProperty); }
            set { SetValue(FillProperty, value); }
        }

        public Brush Stroke
        {
            get { return (Brush)GetValue(StrokeProperty); }
            set { SetValue(StrokeProperty, value); }
        }

        public double StrokeThickness
        {
            get { return (double)GetValue(StrokeThicknessProperty); }
            set { SetValue(StrokeThicknessProperty, value); }
        }

        protected override Size MeasureOverride(Size availableSize)
        {
            if (string.IsNullOrEmpty(Text)) return new Size(0, 0);
            var formattedText = CreateFormattedText(availableSize.Width);
            return new Size(formattedText.Width + StrokeThickness, formattedText.Height + StrokeThickness);
        }

        protected override void OnRender(DrawingContext drawingContext)
        {
            if (string.IsNullOrEmpty(Text)) return;

            var formattedText = CreateFormattedText(ActualWidth);
            
            // Draw a tiny bit offset to avoid clipping the stroke outline
            var geometry = formattedText.BuildGeometry(new Point(StrokeThickness / 2, StrokeThickness / 2));

            // Use PenLineJoin.Round to make corners perfectly rounded and legible
            Pen pen = new Pen(Stroke, StrokeThickness)
            {
                LineJoin = PenLineJoin.Round
            };

            drawingContext.DrawGeometry(Fill, pen, geometry);
        }

        private FormattedText CreateFormattedText(double maxWidth)
        {
            var formattedText = new FormattedText(
                Text,
                CultureInfo.CurrentUICulture,
                FlowDirection.LeftToRight,
                new Typeface(FontFamily, FontStyles.Normal, FontWeights.Bold, FontStretches.Normal),
                FontSize,
                Brushes.Black); // Color doesn't matter since we build geometry from it

            if (!double.IsInfinity(maxWidth) && maxWidth > 0)
            {
                formattedText.MaxTextWidth = Math.Max(10, maxWidth - StrokeThickness);
            }

            return formattedText;
        }
    }
}
